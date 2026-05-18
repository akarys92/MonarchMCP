#!/usr/bin/env python3
"""
Monarch Money MCP Server - MVP
A minimal Model Context Protocol server for Monarch Money with robust login handling.
"""

import os
import sys
import asyncio
import json
from typing import Optional
from pathlib import Path

from dotenv import load_dotenv
from mcp.server import Server
from mcp.types import Tool, TextContent
from monarchmoney import MonarchMoney, RequireMFAException

# Load .env file from the same directory as this script
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    load_dotenv(env_path)
    print(f"[MonarchMCP] ======== SERVER STARTING v2.0 ========", file=sys.stderr, flush=True)
    print(f"[MonarchMCP] Loaded environment from {env_path}", file=sys.stderr, flush=True)
else:
    print(f"[MonarchMCP] ======== SERVER STARTING v2.0 ========", file=sys.stderr, flush=True)
    print(f"[MonarchMCP] No .env file found, using environment variables", file=sys.stderr, flush=True)

# Initialize MCP server
server = Server("monarchmoney")

# Global state
_mm_instance: Optional[MonarchMoney] = None
_login_lock = asyncio.Lock()


def log_debug(message: str):
    """Log debug message to stderr (visible in MCP logs)."""
    print(f"[MonarchMCP] {message}", file=sys.stderr, flush=True)


async def get_mm_with_retry() -> MonarchMoney:
    """
    Get or create MonarchMoney instance with robust login handling.

    Features:
    - Uses saved sessions when possible for speed
    - Retries on transient failures (404, 525, connection errors)
    - Falls back to fresh login if saved session fails
    - Thread-safe with async lock
    - Never caches failed login attempts - always retries on next call
    """
    global _mm_instance

    async with _login_lock:
        # Only return cached instance if it exists and is valid
        # Don't cache None - always retry login if previous attempt failed
        if _mm_instance is not None:
            return _mm_instance

        # Load credentials
        email = os.getenv("MONARCH_EMAIL")
        password = os.getenv("MONARCH_PASSWORD")
        mfa_secret = os.getenv("MONARCH_MFA_SECRET")

        if not email or not password:
            raise ValueError(
                "Missing credentials. Set MONARCH_EMAIL and MONARCH_PASSWORD environment variables."
            )

        log_debug(f"Initializing login for {email[:3]}***{email[-10:]}")
        log_debug(f"MFA configured: {bool(mfa_secret)}")

        # Use the same session directory structure as the library default (.mm/mm_session.pickle)
        # but in the home directory to ensure it's writable
        session_dir = Path.home() / ".mm"
        session_dir.mkdir(exist_ok=True)
        session_file = session_dir / "mm_session.pickle"
        log_debug(f"Using session file: {session_file}")

        # Attempt 1: Try with saved session (fast path)
        _mm_instance = MonarchMoney(session_file=str(session_file))
        try:
            log_debug("Attempting login with saved session...")
            await _mm_instance.login(
                email=email,
                password=password,
                save_session=True,
                use_saved_session=True,
                mfa_secret_key=mfa_secret,
            )
            log_debug("Login successful (used saved session)")
            return _mm_instance

        except RequireMFAException:
            if not mfa_secret:
                raise ValueError(
                    "MFA required but MONARCH_MFA_SECRET not set. "
                    "Add your TOTP secret to the environment."
                )
            raise ValueError("MFA authentication failed even with secret provided")

        except Exception as e:
            error_str = str(e)
            error_type = type(e).__name__
            log_debug(f"Saved session login failed:")
            log_debug(f"  Error type: {error_type}")
            log_debug(f"  Error message: {error_str}")
            log_debug(f"  Full exception: {repr(e)}")

            # Check if it's a transient error worth retrying
            transient_errors = ["404", "525", "429", "ConnectionError", "TimeoutError"]
            is_transient = any(err in error_str for err in transient_errors)

            if "429" in error_str:
                # Don't cache the error - allow retry on next call
                log_debug("DETECTED AS RATE LIMIT - Check if this is correct!")
                raise ValueError(
                    f"Rate limited by Monarch Money. Please wait 5-10 minutes before trying again. (Original: {error_str})"
                )

            # Attempt 2: Fresh login (no saved session)
            if is_transient or "401" in error_str or "Unauthorized" in error_str:
                log_debug("Retrying with fresh login (no saved session)...")
                await asyncio.sleep(2)  # Brief delay before retry

                _mm_instance = MonarchMoney(session_file=str(session_file))
                try:
                    await _mm_instance.login(
                        email=email,
                        password=password,
                        save_session=True,  # Save for next time
                        use_saved_session=False,  # Don't use old session
                        mfa_secret_key=mfa_secret,
                    )
                    log_debug("Login successful (fresh login)")
                    return _mm_instance

                except RequireMFAException:
                    raise ValueError("MFA required but authentication failed")

                except Exception as retry_error:
                    retry_str = str(retry_error)
                    retry_type = type(retry_error).__name__
                    log_debug(f"Retry failed:")
                    log_debug(f"  Error type: {retry_type}")
                    log_debug(f"  Error message: {retry_str}")
                    log_debug(f"  Full exception: {repr(retry_error)}")

                    # Provide helpful error messages
                    if "429" in retry_str:
                        log_debug("DETECTED AS RATE LIMIT ON RETRY - Check if this is correct!")
                        raise ValueError(f"Rate limited. Wait 5-10 minutes before retrying. (Original: {retry_str})")
                    elif "404" in retry_str:
                        raise ValueError(
                            "Monarch Money API returned 404. This may be a temporary issue. "
                            "Try again in a few minutes."
                        )
                    else:
                        raise ValueError(f"Login failed: {retry_str}")
            else:
                raise ValueError(f"Login failed: {error_str}")


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available MCP tools."""
    return [
        # Read-only tools (no approval needed)
        Tool(
            name="get_accounts",
            description="Retrieves all accounts linked to Monarch Money, including balances, types, and status.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="get_transactions",
            description="Retrieves transactions with optional filters for date range, account, category, etc.",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {"type": "number", "description": "Maximum number of transactions to return (default: 100)"},
                    "start_date": {"type": "string", "description": "Start date in YYYY-MM-DD format"},
                    "end_date": {"type": "string", "description": "End date in YYYY-MM-DD format"},
                    "account_id": {"type": "string", "description": "Filter by specific account ID"},
                    "category_id": {"type": "string", "description": "Filter by specific category ID"},
                },
            },
        ),
        Tool(
            name="get_transaction_categories",
            description="Retrieves all transaction categories and their details.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="get_budgets",
            description="Retrieves budget data including spending limits and actual spending.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="get_cashflow",
            description="Retrieves cashflow data showing income and expenses over time.",
            inputSchema={
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date in YYYY-MM-DD format"},
                    "end_date": {"type": "string", "description": "End date in YYYY-MM-DD format"},
                },
            },
        ),
        Tool(
            name="get_cashflow_summary",
            description="Retrieves a summary of cashflow including total income, expenses, and net cashflow.",
            inputSchema={
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date in YYYY-MM-DD format"},
                    "end_date": {"type": "string", "description": "End date in YYYY-MM-DD format"},
                },
            },
        ),
        Tool(
            name="get_account_holdings",
            description="Retrieves investment holdings for a specific account.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account_id": {"type": "string", "description": "The account ID to get holdings for", "required": True},
                },
                "required": ["account_id"],
            },
        ),
        Tool(
            name="get_transaction_details",
            description="Retrieves detailed information about a specific transaction.",
            inputSchema={
                "type": "object",
                "properties": {
                    "transaction_id": {"type": "string", "description": "The transaction ID", "required": True},
                },
                "required": ["transaction_id"],
            },
        ),

        # Write operations (require user approval)
        Tool(
            name="create_transaction",
            description="Creates a new manual transaction. Requires user approval.",
            inputSchema={
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "Transaction date in YYYY-MM-DD format", "required": True},
                    "amount": {"type": "number", "description": "Transaction amount (positive for income, negative for expense)", "required": True},
                    "merchant": {"type": "string", "description": "Merchant or payee name", "required": True},
                    "account_id": {"type": "string", "description": "Account ID for this transaction", "required": True},
                    "category_id": {"type": "string", "description": "Category ID for this transaction"},
                    "notes": {"type": "string", "description": "Additional notes"},
                },
                "required": ["date", "amount", "merchant", "account_id"],
            },
        ),
        Tool(
            name="update_transaction",
            description="Updates an existing transaction. Requires user approval.",
            inputSchema={
                "type": "object",
                "properties": {
                    "transaction_id": {"type": "string", "description": "The transaction ID to update", "required": True},
                    "category_id": {"type": "string", "description": "New category ID"},
                    "merchant": {"type": "string", "description": "New merchant name"},
                    "notes": {"type": "string", "description": "New notes"},
                },
                "required": ["transaction_id"],
            },
        ),
        Tool(
            name="delete_transaction",
            description="Deletes a transaction. Requires user approval.",
            inputSchema={
                "type": "object",
                "properties": {
                    "transaction_id": {"type": "string", "description": "The transaction ID to delete", "required": True},
                },
                "required": ["transaction_id"],
            },
        ),
        Tool(
            name="set_budget_amount",
            description="Sets or updates a budget amount for a category. Requires user approval.",
            inputSchema={
                "type": "object",
                "properties": {
                    "category_id": {"type": "string", "description": "Category ID to set budget for", "required": True},
                    "amount": {"type": "number", "description": "Budget amount", "required": True},
                    "start_date": {"type": "string", "description": "Start date in YYYY-MM-DD format"},
                },
                "required": ["category_id", "amount"],
            },
        ),

        # Additional account management tools
        Tool(
            name="get_account_type_options",
            description="Retrieves a list of available account types and their subtypes. Useful for creating manual accounts.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="create_manual_account",
            description="Creates a new manual account. Requires user approval.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account_type": {"type": "string", "description": "Account type (e.g., loan, other_liability, other_asset, brokerage, depository)", "required": True},
                    "account_sub_type": {"type": "string", "description": "Account subtype (e.g., auto, commercial, mortgage, checking, savings)", "required": True},
                    "account_name": {"type": "string", "description": "Name for the account", "required": True},
                    "account_balance": {"type": "number", "description": "Initial balance (default: 0)"},
                    "is_in_net_worth": {"type": "boolean", "description": "Include in net worth calculation (default: true)"},
                },
                "required": ["account_type", "account_sub_type", "account_name"],
            },
        ),
        Tool(
            name="update_account",
            description="Updates account details. Requires user approval.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account_id": {"type": "string", "description": "The account ID to update", "required": True},
                    "account_name": {"type": "string", "description": "New account name"},
                    "account_balance": {"type": "number", "description": "New account balance"},
                    "account_type": {"type": "string", "description": "New account type"},
                    "account_sub_type": {"type": "string", "description": "New account subtype"},
                    "include_in_net_worth": {"type": "boolean", "description": "Include in net worth calculation"},
                    "hide_from_list": {"type": "boolean", "description": "Hide from accounts list"},
                    "hide_transactions_from_reports": {"type": "boolean", "description": "Hide transactions from reports"},
                },
                "required": ["account_id"],
            },
        ),
        Tool(
            name="delete_account",
            description="Deletes an account. Requires user approval.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account_id": {"type": "string", "description": "The account ID to delete", "required": True},
                },
                "required": ["account_id"],
            },
        ),
        Tool(
            name="get_account_history",
            description="Gets historical balance snapshots and recent transactions for an account.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account_id": {"type": "string", "description": "The account ID to get history for", "required": True},
                },
                "required": ["account_id"],
            },
        ),
        Tool(
            name="get_recent_account_balances",
            description="Retrieves daily balance history for all accounts from the specified start date.",
            inputSchema={
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date in YYYY-MM-DD format (default: 31 days ago)"},
                },
            },
        ),
        Tool(
            name="get_aggregate_snapshots",
            description="Retrieves daily net worth snapshots, optionally filtered by date range and account type.",
            inputSchema={
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date in YYYY-MM-DD format"},
                    "end_date": {"type": "string", "description": "End date in YYYY-MM-DD format"},
                    "account_type": {"type": "string", "description": "Filter by account type"},
                },
            },
        ),
        Tool(
            name="get_account_snapshots_by_type",
            description="Retrieves snapshots of account balances grouped by type over time.",
            inputSchema={
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date in YYYY-MM-DD format", "required": True},
                    "timeframe": {"type": "string", "description": "Timeframe: 'month' or 'year'", "required": True},
                },
                "required": ["start_date", "timeframe"],
            },
        ),

        # Account refresh tools
        Tool(
            name="request_accounts_refresh",
            description="Requests Monarch to refresh account balances and transactions from linked institutions. Requires user approval.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account_ids": {"type": "array", "items": {"type": "string"}, "description": "List of account IDs to refresh", "required": True},
                },
                "required": ["account_ids"],
            },
        ),
        Tool(
            name="is_accounts_refresh_complete",
            description="Checks if a previously requested account refresh is complete.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account_ids": {"type": "array", "items": {"type": "string"}, "description": "List of account IDs to check (optional, checks all if not specified)"},
                },
            },
        ),
        Tool(
            name="request_accounts_refresh_and_wait",
            description="Refreshes accounts and waits for completion. Requires user approval.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account_ids": {"type": "array", "items": {"type": "string"}, "description": "List of account IDs to refresh (optional, refreshes all if not specified)"},
                    "timeout": {"type": "number", "description": "Timeout in seconds (default: 300)"},
                },
            },
        ),

        # Transaction management tools
        Tool(
            name="get_transactions_summary",
            description="Gets summary statistics for transactions (avg, count, max, sum, etc.).",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="get_transaction_splits",
            description="Gets split transaction details for a transaction.",
            inputSchema={
                "type": "object",
                "properties": {
                    "transaction_id": {"type": "string", "description": "The transaction ID", "required": True},
                },
                "required": ["transaction_id"],
            },
        ),
        Tool(
            name="update_transaction_splits",
            description="Creates, modifies, or deletes splits for a transaction. Requires user approval.",
            inputSchema={
                "type": "object",
                "properties": {
                    "transaction_id": {"type": "string", "description": "The transaction ID to split", "required": True},
                    "split_data": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "merchantName": {"type": "string"},
                                "amount": {"type": "number"},
                                "categoryId": {"type": "string"},
                            },
                        },
                        "description": "Array of split objects. Empty array removes all splits. Sum of amounts must equal original transaction amount.",
                    },
                },
                "required": ["transaction_id"],
            },
        ),

        # Category management tools
        Tool(
            name="get_transaction_category_groups",
            description="Retrieves all transaction category groups.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="create_transaction_category",
            description="Creates a new transaction category. Requires user approval.",
            inputSchema={
                "type": "object",
                "properties": {
                    "group_id": {"type": "string", "description": "The category group ID", "required": True},
                    "name": {"type": "string", "description": "Name of the new category", "required": True},
                    "icon": {"type": "string", "description": "Icon for the category (unicode/emoji, default: question mark)"},
                    "rollover_enabled": {"type": "boolean", "description": "Enable budget rollover (default: false)"},
                    "rollover_type": {"type": "string", "description": "Rollover type (default: 'monthly')"},
                },
                "required": ["group_id", "name"],
            },
        ),
        Tool(
            name="delete_transaction_category",
            description="Deletes a transaction category. Requires user approval.",
            inputSchema={
                "type": "object",
                "properties": {
                    "category_id": {"type": "string", "description": "The category ID to delete", "required": True},
                },
                "required": ["category_id"],
            },
        ),

        # Tag management tools
        Tool(
            name="get_transaction_tags",
            description="Retrieves all transaction tags.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="create_transaction_tag",
            description="Creates a new transaction tag. Requires user approval.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Name of the tag", "required": True},
                    "color": {"type": "string", "description": "Color in hex format (e.g., '#19D2A5')", "required": True},
                },
                "required": ["name", "color"],
            },
        ),
        Tool(
            name="set_transaction_tags",
            description="Sets tags on a transaction (overwrites existing tags). Requires user approval.",
            inputSchema={
                "type": "object",
                "properties": {
                    "transaction_id": {"type": "string", "description": "The transaction ID", "required": True},
                    "tag_ids": {"type": "array", "items": {"type": "string"}, "description": "List of tag IDs to set (empty list removes all tags)", "required": True},
                },
                "required": ["transaction_id", "tag_ids"],
            },
        ),

        # Financial data tools
        Tool(
            name="get_institutions",
            description="Retrieves information about linked financial institutions.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="get_subscription_details",
            description="Retrieves Monarch Money subscription details (plan type, trial status, etc.).",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="get_recurring_transactions",
            description="Retrieves upcoming recurring transactions (subscriptions, bills, etc.).",
            inputSchema={
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date in YYYY-MM-DD format"},
                    "end_date": {"type": "string", "description": "End date in YYYY-MM-DD format"},
                },
            },
        ),
        Tool(
            name="get_credit_history",
            description="Retrieves credit score history and related details.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle tool execution."""
    log_debug(f"========== TOOL CALLED: {name} ==========")
    try:
        # Get authenticated instance
        log_debug("About to call get_mm_with_retry()...")
        mm = await get_mm_with_retry()
        log_debug("get_mm_with_retry() returned successfully")

        # Read-only operations
        if name == "get_accounts":
            log_debug("Fetching accounts...")
            result = await mm.get_accounts()
            log_debug(f"Successfully retrieved {len(result.get('accounts', []))} accounts")
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "get_transactions":
            log_debug("Fetching transactions...")
            result = await mm.get_transactions(
                limit=arguments.get("limit", 100),
                start_date=arguments.get("start_date"),
                end_date=arguments.get("end_date"),
                account_id=arguments.get("account_id"),
                category_id=arguments.get("category_id"),
            )
            log_debug(f"Successfully retrieved transactions")
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "get_transaction_categories":
            log_debug("Fetching transaction categories...")
            result = await mm.get_transaction_categories()
            log_debug(f"Successfully retrieved categories")
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "get_budgets":
            log_debug("Fetching budgets...")
            result = await mm.get_budgets()
            log_debug(f"Successfully retrieved budgets")
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "get_cashflow":
            log_debug("Fetching cashflow...")
            result = await mm.get_cashflow(
                start_date=arguments.get("start_date"),
                end_date=arguments.get("end_date"),
            )
            log_debug(f"Successfully retrieved cashflow")
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "get_cashflow_summary":
            log_debug("Fetching cashflow summary...")
            result = await mm.get_cashflow_summary(
                start_date=arguments.get("start_date"),
                end_date=arguments.get("end_date"),
            )
            log_debug(f"Successfully retrieved cashflow summary")
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "get_account_holdings":
            log_debug("Fetching account holdings...")
            account_id = arguments.get("account_id")
            if not account_id:
                raise ValueError("account_id is required")
            result = await mm.get_account_holdings(account_id=account_id)
            log_debug(f"Successfully retrieved holdings")
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "get_transaction_details":
            log_debug("Fetching transaction details...")
            transaction_id = arguments.get("transaction_id")
            if not transaction_id:
                raise ValueError("transaction_id is required")
            result = await mm.get_transaction_details(transaction_id=transaction_id)
            log_debug(f"Successfully retrieved transaction details")
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        # Write operations (require user approval via MCP)
        elif name == "create_transaction":
            log_debug("Creating transaction...")
            result = await mm.create_transaction(
                date=arguments.get("date"),
                amount=arguments.get("amount"),
                merchant_name=arguments.get("merchant"),
                account_id=arguments.get("account_id"),
                category_id=arguments.get("category_id"),
                notes=arguments.get("notes"),
            )
            log_debug(f"Successfully created transaction")
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "update_transaction":
            log_debug("Updating transaction...")
            transaction_id = arguments.get("transaction_id")
            if not transaction_id:
                raise ValueError("transaction_id is required")
            result = await mm.update_transaction(
                transaction_id=transaction_id,
                category_id=arguments.get("category_id"),
                merchant_name=arguments.get("merchant"),
                notes=arguments.get("notes"),
            )
            log_debug(f"Successfully updated transaction")
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "delete_transaction":
            log_debug("Deleting transaction...")
            transaction_id = arguments.get("transaction_id")
            if not transaction_id:
                raise ValueError("transaction_id is required")
            result = await mm.delete_transaction(transaction_id=transaction_id)
            log_debug(f"Successfully deleted transaction")
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "set_budget_amount":
            log_debug("Setting budget amount...")
            result = await mm.set_budget_amount(
                category_id=arguments.get("category_id"),
                amount=arguments.get("amount"),
                start_date=arguments.get("start_date"),
            )
            log_debug(f"Successfully set budget amount")
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        # Additional account management tools
        elif name == "get_account_type_options":
            log_debug("Fetching account type options...")
            result = await mm.get_account_type_options()
            log_debug(f"Successfully retrieved account type options")
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "create_manual_account":
            log_debug("Creating manual account...")
            result = await mm.create_manual_account(
                account_type=arguments.get("account_type"),
                account_sub_type=arguments.get("account_sub_type"),
                account_name=arguments.get("account_name"),
                account_balance=arguments.get("account_balance", 0),
                is_in_net_worth=arguments.get("is_in_net_worth", True),
            )
            log_debug(f"Successfully created manual account")
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "update_account":
            log_debug("Updating account...")
            account_id = arguments.get("account_id")
            if not account_id:
                raise ValueError("account_id is required")
            result = await mm.update_account(
                account_id=account_id,
                account_name=arguments.get("account_name"),
                account_balance=arguments.get("account_balance"),
                account_type=arguments.get("account_type"),
                account_sub_type=arguments.get("account_sub_type"),
                include_in_net_worth=arguments.get("include_in_net_worth"),
                hide_from_summary_list=arguments.get("hide_from_list"),
                hide_transactions_from_reports=arguments.get("hide_transactions_from_reports"),
            )
            log_debug(f"Successfully updated account")
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "delete_account":
            log_debug("Deleting account...")
            account_id = arguments.get("account_id")
            if not account_id:
                raise ValueError("account_id is required")
            result = await mm.delete_account(account_id=account_id)
            log_debug(f"Successfully deleted account")
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "get_account_history":
            log_debug("Fetching account history...")
            account_id = arguments.get("account_id")
            if not account_id:
                raise ValueError("account_id is required")
            result = await mm.get_account_history(account_id=account_id)
            log_debug(f"Successfully retrieved account history")
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "get_recent_account_balances":
            log_debug("Fetching recent account balances...")
            result = await mm.get_recent_account_balances(
                start_date=arguments.get("start_date"),
            )
            log_debug(f"Successfully retrieved recent account balances")
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "get_aggregate_snapshots":
            log_debug("Fetching aggregate snapshots...")
            result = await mm.get_aggregate_snapshots(
                start_date=arguments.get("start_date"),
                end_date=arguments.get("end_date"),
                account_type=arguments.get("account_type"),
            )
            log_debug(f"Successfully retrieved aggregate snapshots")
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "get_account_snapshots_by_type":
            log_debug("Fetching account snapshots by type...")
            start_date = arguments.get("start_date")
            timeframe = arguments.get("timeframe")
            if not start_date or not timeframe:
                raise ValueError("start_date and timeframe are required")
            result = await mm.get_account_snapshots_by_type(
                start_date=start_date,
                timeframe=timeframe,
            )
            log_debug(f"Successfully retrieved account snapshots by type")
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        # Account refresh tools
        elif name == "request_accounts_refresh":
            log_debug("Requesting accounts refresh...")
            account_ids = arguments.get("account_ids")
            if not account_ids:
                raise ValueError("account_ids is required")
            result = await mm.request_accounts_refresh(account_ids=account_ids)
            log_debug(f"Successfully requested accounts refresh")
            return [TextContent(type="text", text=json.dumps({"success": result}, indent=2))]

        elif name == "is_accounts_refresh_complete":
            log_debug("Checking if accounts refresh is complete...")
            result = await mm.is_accounts_refresh_complete(
                account_ids=arguments.get("account_ids"),
            )
            log_debug(f"Accounts refresh complete: {result}")
            return [TextContent(type="text", text=json.dumps({"complete": result}, indent=2))]

        elif name == "request_accounts_refresh_and_wait":
            log_debug("Requesting accounts refresh and waiting...")
            result = await mm.request_accounts_refresh_and_wait(
                account_ids=arguments.get("account_ids"),
                timeout=arguments.get("timeout", 300),
            )
            log_debug(f"Accounts refresh completed: {result}")
            return [TextContent(type="text", text=json.dumps({"completed": result}, indent=2))]

        # Transaction management tools
        elif name == "get_transactions_summary":
            log_debug("Fetching transactions summary...")
            result = await mm.get_transactions_summary()
            log_debug(f"Successfully retrieved transactions summary")
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "get_transaction_splits":
            log_debug("Fetching transaction splits...")
            transaction_id = arguments.get("transaction_id")
            if not transaction_id:
                raise ValueError("transaction_id is required")
            result = await mm.get_transaction_splits(transaction_id=transaction_id)
            log_debug(f"Successfully retrieved transaction splits")
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "update_transaction_splits":
            log_debug("Updating transaction splits...")
            transaction_id = arguments.get("transaction_id")
            if not transaction_id:
                raise ValueError("transaction_id is required")
            result = await mm.update_transaction_splits(
                transaction_id=transaction_id,
                split_data=arguments.get("split_data", []),
            )
            log_debug(f"Successfully updated transaction splits")
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        # Category management tools
        elif name == "get_transaction_category_groups":
            log_debug("Fetching transaction category groups...")
            result = await mm.get_transaction_category_groups()
            log_debug(f"Successfully retrieved category groups")
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "create_transaction_category":
            log_debug("Creating transaction category...")
            group_id = arguments.get("group_id")
            name_arg = arguments.get("name")
            if not group_id or not name_arg:
                raise ValueError("group_id and name are required")
            result = await mm.create_transaction_category(
                group_id=group_id,
                transaction_category_name=name_arg,
                icon=arguments.get("icon", "\u2753"),
                rollover_enabled=arguments.get("rollover_enabled", False),
                rollover_type=arguments.get("rollover_type", "monthly"),
            )
            log_debug(f"Successfully created transaction category")
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "delete_transaction_category":
            log_debug("Deleting transaction category...")
            category_id = arguments.get("category_id")
            if not category_id:
                raise ValueError("category_id is required")
            result = await mm.delete_transaction_category(category_id=category_id)
            log_debug(f"Successfully deleted transaction category")
            return [TextContent(type="text", text=json.dumps({"deleted": result}, indent=2))]

        # Tag management tools
        elif name == "get_transaction_tags":
            log_debug("Fetching transaction tags...")
            result = await mm.get_transaction_tags()
            log_debug(f"Successfully retrieved transaction tags")
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "create_transaction_tag":
            log_debug("Creating transaction tag...")
            name_arg = arguments.get("name")
            color = arguments.get("color")
            if not name_arg or not color:
                raise ValueError("name and color are required")
            result = await mm.create_transaction_tag(name=name_arg, color=color)
            log_debug(f"Successfully created transaction tag")
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "set_transaction_tags":
            log_debug("Setting transaction tags...")
            transaction_id = arguments.get("transaction_id")
            tag_ids = arguments.get("tag_ids")
            if not transaction_id or tag_ids is None:
                raise ValueError("transaction_id and tag_ids are required")
            result = await mm.set_transaction_tags(
                transaction_id=transaction_id,
                tag_ids=tag_ids,
            )
            log_debug(f"Successfully set transaction tags")
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        # Financial data tools
        elif name == "get_institutions":
            log_debug("Fetching institutions...")
            result = await mm.get_institutions()
            log_debug(f"Successfully retrieved institutions")
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "get_subscription_details":
            log_debug("Fetching subscription details...")
            result = await mm.get_subscription_details()
            log_debug(f"Successfully retrieved subscription details")
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "get_recurring_transactions":
            log_debug("Fetching recurring transactions...")
            result = await mm.get_recurring_transactions(
                start_date=arguments.get("start_date"),
                end_date=arguments.get("end_date"),
            )
            log_debug(f"Successfully retrieved recurring transactions")
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "get_credit_history":
            log_debug("Fetching credit history...")
            result = await mm.get_credit_history()
            log_debug(f"Successfully retrieved credit history")
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        else:
            raise ValueError(f"Unknown tool: {name}")

    except Exception as e:
        error_msg = str(e)
        log_debug(f"Tool execution error: {error_msg}")
        return [TextContent(type="text", text=f"Error: {error_msg}")]


async def main():
    """Run the MCP server."""
    from mcp.server.stdio import stdio_server

    log_debug("Starting Monarch Money MCP Server (MVP)")

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
