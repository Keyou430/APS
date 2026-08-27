# Source Frontend Replacement Design

## Goal

Replace `D:\Replica1.0\web-platform` with the frontend from
`D:\星纪云v1.0\agent-platform-system\web-platform`, preserving that source
frontend's layout, styles, navigation, submenu-to-card behavior, tabs, and
responsive behavior while connecting it to the current Replica backend.

## Source Of Truth

The source project is authoritative for all user-visible frontend behavior.
This includes `index.html`, `styles.css`, the legacy application shell,
React pages, icons, navigation structure, submenu state, compound tabs,
card scrolling and highlighting, and custom website navigation.

The current Replica frontend is not a visual or interaction source. Its code
may be retained only where it is required to satisfy a current backend API
contract and does not alter the source frontend's presentation or navigation.

## Replacement Boundary

Replace the complete `web-platform` source tree, excluding generated and local
dependency directories such as `node_modules`, `dist`, `test-results`, and
locally generated screenshot artifacts. Files that exist only in the current
frontend implementation are removed when they are not part of a required API
adapter.

Backend code, uploads, migrations, backend tests, deployment files, and other
repository directories are outside this replacement boundary and remain
unchanged.

## Backend Alignment

After copying the source frontend, align it with the current FastAPI backend at
the frontend contract boundary:

- Keep the `/api` base path and Vite development proxy to port 8000.
- Preserve the current single-user authentication behavior, including
  anonymous `/api/auth/me` use and avoiding refresh loops when no bearer token
  exists.
- Preserve current DTO and request changes for users, chat knowledge scope,
  dashboard decisions, pipeline approvals, enterprise announcements, and
  numeric knowledge citation identifiers.
- Prefer changes in `src/api`, authentication runtime, and narrow event bridges.
  Do not redesign source pages to accommodate backend differences.
- Keep source UI modules whose backend contracts do not exist. Their existing
  explicit unsupported/error behavior remains; no mock success response or new
  backend subsystem is introduced by this frontend replacement.

## Navigation And Interaction

The legacy shell behavior is restored as implemented by the source project.
In particular, dashboard and portal submenu clicks must open the parent view,
create or activate the corresponding compound tab, scroll to the selected
card, flash-highlight it, and synchronize sidebar selection. AI services,
account management, work platform, custom websites, and dynamic subsystem
navigation keep their source behavior.

## Verification

Verification covers:

1. Source and destination frontend manifests match apart from documented
   backend adapters and excluded generated files.
2. Node contract tests and Vitest tests pass.
3. TypeScript and the Vite production build pass.
4. Backend contract tests relevant to authentication, dashboard decisions,
   pipeline approval, users, chat, and knowledge pass.
5. Browser checks confirm desktop and mobile rendering, primary navigation,
   submenu-to-card scrolling/highlighting, tab creation, and absence of
   overlapping or blank UI.

## Acceptance Criteria

- The running Replica frontend visually and behaviorally follows the source
  frontend rather than the current Replica redesign.
- Source submenu-to-card navigation and tab behavior work.
- Supported screens load current backend data without mock fallbacks.
- The app builds successfully and critical frontend/backend contract tests pass.
- No files outside the frontend boundary are overwritten as part of the copy.
