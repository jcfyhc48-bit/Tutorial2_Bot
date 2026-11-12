# Telegram Membership + Groq Vision Bot

## Railway Variables
Set these in Railway → Service → Variables:

- `BOT_TOKEN` = BotFather token
- `GROQ_API_KEY` = Groq API key
- `CREATOR_ID` = `5188275898`
- `MAIN_CHANNEL_ID` = `@seriesmoviesplanet007`
- `VIP_CHANNEL_ID` = `-1004375167843`
- `ADMIN_USERNAME` = `Nazzpar`
- `PAYMENT_NAME` = `NYEIN SOPYAY AUNG`
- `AI_REQUIRED_NAME` = `MG NYEIN SOPYAY AUNG`
- `PAYMENT_PHONE_LAST4` = `8562`
- `PAYMENT_AMOUNT` = `100`
- `DB_PATH` = `/data/bot.db`
- `GROQ_MODEL` = `qwen/qwen3.8-27b`

## Railway setup
1. Upload/push these files to a GitHub repository.
2. Create a Railway project and deploy the repository.
3. Add all variables above.
4. Add a Railway Volume and mount it at `/data` so SQLite data survives redeploys.
5. Set the start command to `python main.py` (or use the included Procfile).
6. Do not run more than one replica of this polling bot.

## Telegram permissions
- Add the bot as an administrator in the Main Channel so it can check membership.
- Add the bot as an administrator in the VIP Channel with permission to invite users.
- Ensure the bot is not restricted from creating invite links.
- The user must have opened the bot at least once for the bot to send them a private message.

## Important payment safety
Groq vision only reads the screenshot and checks visible text. It cannot confirm that money reached the KBZPay account and cannot reliably prove that an image is authentic. The bot therefore sends every receipt to the Creator and only issues a VIP invite link after the Creator presses Approve. Check the actual KBZPay transaction in the receiving account before approving.

The receipt duplicate checks use SHA-256 image hashes and unique transaction IDs. A visually modified copy may evade the image hash check; manual payment verification remains essential.

## Notes
- Each approved receipt creates an invite link with `member_limit=1` and a 24-hour expiry.
- The 24-hour expiry applies to the invite link, not to the lifetime membership after joining.
- If a link expires unused, ask the Creator to review/reissue it; do not forward the same link to another person.
