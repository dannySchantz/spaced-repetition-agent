# SMS simulator and authorized live setup

## Free local demonstration

```sh
recall serve
# Separate terminal:
recall add kernel 'Inputs mapped to zero'
recall add rank 'Dimension of the image'
recall add eigenvector 'A nonzero vector scaled by a linear transformation.'
recall sms setup
recall sms simulate MORE
# Use the returned code and item numbers:
recall sms simulate 'AB12 1) Inputs mapped to zero; 2) Dimension of the image; 3) A vector scaled by the matrix.'
recall sms simulate 'AB12 3) It must be nonzero.'
```

`recall sms setup` explicitly opts in to the local simulator. It cannot enable Twilio.
STOP persists until START; invoking simulate again does not silently opt you back in.
Offline fixture grading recognizes the documented answers and the evaluation fixtures.
Other answers remain pending; use manual TUI ratings. See simulator-transcript.md for
the actual generated local exchange. No simulator transcript is a real phone test.

## Remaining live steps (not performed)

1. Confirm the recipient country, consenting owner number, sender type, allowed segment
   and AI token budgets, and exact authorization to send. No account purchase, number
   rental, deployment, API charge or real text is authorized by the implementation work.
2. Set up Twilio and a two-way SMS sender. Check current sender requirements for the
   actual country/type. For US local 10-digit senders, investigate A2P registration;
   toll-free senders have a separate verification path. Wait for required approvals.
3. Configure opt-out handling and any required sender identification/onboarding text
   for the chosen messaging program. Test provider STOP/START/HELP behavior. The app
   honors `OptOutType` and avoids duplicate provider-handled replies. RESUME cannot
   override STOP. App consent never substitutes for sender registration.
4. Configure secrets and explicit flags on the authorized service:
   `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `RECALL_OWNER_PHONE`, `RECALL_SENDER_PHONE`,
   `RECALL_PUBLIC_URL`, strong `RECALL_TOKEN`, `RECALL_OWNER_CONSENT=yes`,
   a positive `RECALL_MONTHLY_SMS_SEGMENTS`, and finally `RECALL_LIVE_SMS=true`.
   Set `RECALL_TOLL_FREE=true` if applicable. Switching adapters cancels unsent old
   messages and requires explicit consent/reactivation on the new transport.
5. Configure the Twilio inbound webhook as `POST https://DOMAIN/webhooks/twilio/inbound`.
   Status callbacks are attached to each outbound request as
   `https://DOMAIN/webhooks/twilio/status/SEND_ATTEMPT_UUID`. The SDK validates all signed
   parameters against the canonical public URL. Only the configured account, owner and
   sender are accepted. Keep the app on HTTPS behind the provided reverse proxy.
6. Send START from the consenting phone after authorization, or explicitly enable the
   owner's consent in Settings when provider opt-out is clear. Start with one card and
   a small allowance. Perform a complete, partial and probing conversation; retry a
   callback; verify TUI/SMS shared completion; test PAUSE, STOP, START and quiet hours.
7. Run the authorized hosted pilot for a week, including laptop sleep, service restart,
   restore, DST/slot observations where applicable and actual segment/token bills.
   Record outcomes in STATUS.md. M7 remains incomplete until observed on the real setup.

## AI enablement

Credentials alone never enable paid grading. `evals/README.md` describes explicitly
opt-in live evaluation. After comparing candidate models and reviewing all labels,
probes and disagreements, mark the passed report `human_reviewed: true`. Set
`RECALL_EVAL_REPORT`, matching `RECALL_MODEL`, a positive `RECALL_MONTHLY_AI_TOKENS`,
and `RECALL_LIVE_AI=true`. Requests reserve a conservative token allowance before calls;
failed/uncertain requests retain the reservation. This is not a dollar-price quote.
Without a passing report, automatic live grading remains disabled; self-rating works.

## Costs and current-provider references

There is no purchased sender, live model choice, approved hosting plan, or total monthly
cost quote yet. Review current rates during setup: number rental + inbound/outbound
segments + carrier/registration fees + AI tokens + hosting/storage/taxes. Inbound texts
and provider-handled control messages can incur charges independently of application
outbound caps. Keep account-level limits/alerts as well as application allowances.
The planning document's numerical illustration must be refreshed before spending.

- [Twilio sender registration](https://www.twilio.com/docs/messaging/compliance/a2p-10dlc)
- [Twilio US messaging pricing](https://www.twilio.com/en-us/sms/pricing/us)
- [Encoding and segment rules](https://www.twilio.com/docs/glossary/what-sms-character-limit)
- [Webhook signature validation](https://www.twilio.com/docs/usage/webhooks/webhooks-security)
- [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
