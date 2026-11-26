# Code signing policy

## Current status

Current Omni PDF releases are unsigned.

## Project roles

- **Committer and reviewer:** [Jakub Hudák](https://github.com/hudakjakub), the project maintainer. Contributions from others are reviewed by a project maintainer.
- **Release approver:** [Jakub Hudák](https://github.com/hudakjakub). Each signing request requires manual approval.

Project members involved in signing must use multifactor authentication for their GitHub and SignPath accounts. Signed binaries must come from verifiable builds of this repository. Third-party binaries are not signed as if they were project-built code.

## Privacy

Omni PDF processes documents locally; it does not upload document contents. Packaged versions check GitHub for updates automatically on startup and periodically unless automatic checks are disabled in the application menu. A manual check also contacts GitHub. These requests expose ordinary network information, such as the user's IP address, to GitHub; see the [GitHub Privacy Statement](https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement). The updated EXE is downloaded after the user agrees to update.
