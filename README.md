# Monarch Money MCP Server

Connect Claude to your Monarch Money account for AI-powered financial analysis and management.

## Quick Start

1. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Get your MFA secret** from Monarch Money Settings → Security → Enable MFA

3. **Configure Claude Desktop** (`~/Library/Application Support/Claude/claude_desktop_config.json`):
   ```json
   {
     "mcpServers": {
       "monarchmoney": {
         "command": "python3",
         "args": ["/absolute/path/to/mcp_server_mvp.py"],
         "env": {
           "MONARCH_EMAIL": "your@email.com",
           "MONARCH_PASSWORD": "your_password",
           "MONARCH_MFA_SECRET": "YOUR_MFA_SECRET"
         }
       }
     }
   }
   ```

4. **Restart Claude Desktop**

## Example Prompts

```
Show me my account balances
What did I spend on groceries last month?
Create a $50 transaction at Target from my checking account
Set my dining budget to $600 this month
Compare my spending to budget
Show my upcoming recurring bills
What's my credit score history?
```

---

## Available Tools (35)

### Accounts

| Tool | Description | Approval |
|------|-------------|----------|
| `get_accounts` | Get all linked accounts with balances | No |
| `get_account_holdings` | Get investment holdings for an account | No |
| `get_account_history` | Get historical balance snapshots | No |
| `get_account_type_options` | List available account types/subtypes | No |
| `get_recent_account_balances` | Get daily balance history | No |
| `get_aggregate_snapshots` | Get daily net worth snapshots | No |
| `get_account_snapshots_by_type` | Get snapshots by account type | No |
| `create_manual_account` | Create a new manual account | Yes |
| `update_account` | Update account details | Yes |
| `delete_account` | Delete an account | Yes |

### Account Sync

| Tool | Description | Approval |
|------|-------------|----------|
| `request_accounts_refresh` | Trigger refresh from institutions | Yes |
| `is_accounts_refresh_complete` | Check if refresh is complete | No |
| `request_accounts_refresh_and_wait` | Refresh and wait for completion | Yes |

### Transactions

| Tool | Description | Approval |
|------|-------------|----------|
| `get_transactions` | Get transactions with filters | No |
| `get_transaction_details` | Get detailed transaction info | No |
| `get_transactions_summary` | Get transaction statistics | No |
| `get_transaction_splits` | Get split transaction details | No |
| `get_recurring_transactions` | Get upcoming bills/subscriptions | No |
| `create_transaction` | Create a manual transaction | Yes |
| `update_transaction` | Update transaction details | Yes |
| `delete_transaction` | Delete a transaction | Yes |
| `update_transaction_splits` | Modify transaction splits | Yes |

### Categories

| Tool | Description | Approval |
|------|-------------|----------|
| `get_transaction_categories` | Get all categories | No |
| `get_transaction_category_groups` | Get category groups | No |
| `create_transaction_category` | Create a new category | Yes |
| `delete_transaction_category` | Delete a category | Yes |

### Tags

| Tool | Description | Approval |
|------|-------------|----------|
| `get_transaction_tags` | Get all tags | No |
| `create_transaction_tag` | Create a tag with color | Yes |
| `set_transaction_tags` | Set tags on a transaction | Yes |

### Budgets

| Tool | Description | Approval |
|------|-------------|----------|
| `get_budgets` | Get budget data with spending limits | No |
| `set_budget_amount` | Set/update budget for a category | Yes |

### Cashflow

| Tool | Description | Approval |
|------|-------------|----------|
| `get_cashflow` | Get income/expense by category | No |
| `get_cashflow_summary` | Get total income, expenses, savings | No |

### Financial Data

| Tool | Description | Approval |
|------|-------------|----------|
| `get_institutions` | Get linked financial institutions | No |
| `get_subscription_details` | Get Monarch subscription info | No |
| `get_credit_history` | Get credit score history | No |

---

## Troubleshooting

**Rate Limited**: Wait 5-10 minutes before retrying.

**MFA Required**: Ensure `MONARCH_MFA_SECRET` is the base32 TOTP secret (not a 6-digit code).

**Check Logs**:
```bash
tail -f ~/Library/Logs/Claude/mcp-server-monarchmoney.log
```

---

## Architecture

```
Claude Desktop ←→ MCP Server ←→ MonarchMoney Library ←→ Monarch Money API
```

- Authenticates using email/password/MFA
- Caches sessions for performance
- Requires approval for write operations

## Requirements

- Python 3.10+
- `monarchmoneycommunity` library
- `mcp` library
- Monarch Money account with MFA enabled

## License

MIT License

## Credits

Built on [monarchmoneycommunity](https://github.com/hammem/monarchmoney) Python library.
