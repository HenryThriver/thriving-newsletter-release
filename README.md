# Thriving newsletter release switchboard

This public repository is a deliberately small, manually protected release
control for newsletter broadcasts. It contains no newsletter copy, subscriber
data, seed addresses, provider receipts, or production credentials.

The private `thriving-henry-website` repository remains the source of truth.
An edition is rendered and seed-tested there, then frozen in a private commit.
This repository accepts that exact commit and a future delivery time, pauses at
the `newsletter-production` environment, and waits for Henry's approval.

Only after that approval does GitHub unlock the production credentials. The
workflow then checks out the frozen private commit, revalidates the edition and
seed receipt, schedules the exact tested content, and pushes the private
schedule receipt to a new branch in the website repository.

In plain English: agents can prepare the package, but Henry has the red button.

## What this repository does not do

- It does not store or edit newsletter content.
- It does not contain audience or Resend identifiers.
- It does not send merely because a pull request merged.
- It does not let an ordinary agent session read the production sending key.
- It does not replace the private editorial and testing workflow.

## Release outline

1. Finish the edition in the private website repository.
2. Send and inspect the two required seed messages.
3. Commit the exact source and seed receipt to a private release commit.
4. Run **Schedule protected newsletter** with that commit and the delivery time.
5. Inspect the pending deployment details and approve
   `newsletter-production` in GitHub.
6. The workflow schedules the broadcast and creates a private receipt branch.
7. Merge the receipt branch into the website repository for the permanent
   audit trail.

The detailed operating procedure lives in the private website repository at
`docs/newsletter/send-runbook.md`.
