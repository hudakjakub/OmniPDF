# Code signing policy

## Current status

Omni PDF is applying for free code signing from SignPath Foundation. The application has not yet been approved and current releases are unsigned.

If accepted, free code signing would be provided by [SignPath.io](https://signpath.io/), with a certificate provided by [SignPath Foundation](https://signpath.org/). Signed releases would identify SignPath Foundation as the publisher.

## Project roles

- **Committer and reviewer:** [Jakub Hudák](https://github.com/hudakjakub), the project maintainer. Contributions from others are reviewed by a project maintainer.
- **Release approver:** [Jakub Hudák](https://github.com/hudakjakub). Each signing request requires manual approval.

Project members involved in signing must use multifactor authentication for their GitHub and SignPath accounts. Signed binaries must come from verifiable builds of this repository. Third-party binaries are not signed as if they were project-built code.

## Privacy

Omni PDF processes documents locally; it does not upload document contents. Packaged versions check GitHub for updates automatically on startup and periodically unless automatic checks are disabled in the application menu. A manual check also contacts GitHub. These requests expose ordinary network information, such as the user's IP address, to GitHub; see the [GitHub Privacy Statement](https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement). An installer is downloaded only after the user agrees to update.
