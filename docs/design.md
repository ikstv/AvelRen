# Design: ROAD SIGN

The canonical design of the Android app. Rules 9 and 10 in `AGENTS.md` carry the
invariants; this file carries the detail — what exists, what does not, and what
is still open.

State: `main` as of 2026-08-20 (`ca36ba5`).

## Where things are

```
design-system/ds/
├── foundations/color.html   palette
├── foundations/type.html    typography
├── components/{buttons,pill-chip,list-row,plate,sign-panel,watch-card}.html
├── screens/onboarding.html  the ONLY screen in the system
└── data/checkpoints.json    fixtures

android/app/src/main/java/ua/avelren/app/ui/
├── theme/Color.kt           tokens — source of truth
├── theme/{Type,Theme}.kt
├── OnboardingScreen.kt
└── AvelRenScreen.kt         the other nine screens live here

android/app/src/main/res/font/   Overpass: regular / bold / black (OFL)
```

The HTML files open directly in a browser; nothing to build.

## Tokens

Signal colours are identical in both themes — they are semantics, not
decoration. Do not repaint them for composition.

| Token | Hex | Role |
|---|---|---|
| `SignGo` | `#0E7A4E` | "go", server online, chart line |
| `SignGoDeep` | `#0A5F3D` | inner line of a sign panel |
| `SignWarn` | `#F5C400` | attention / rising — the de facto brand colour |
| `SignClosed` | `#D5382C` | closed, paused, "no internet" |

Neutrals, light → dark: `paper` `#F4F5F3` → `#16181A`, `panel` `#FFFFFF` →
`#1F2224`, `ink` `#1C1E20` → `#F2F4F1`, `ink2` `#5B6065` → `#9AA0A6`, `line`
`#D9DCD8` → `#2A2E31`, `frame` `#FFFFFF` → `#E8ECE8`.

Typeface: **Overpass**, which derives from Highway Gothic — the same lineage as
the road-sign metaphor.

## Screen inventory

Everything except onboarding lives in `AvelRenScreen.kt`.

| # | Screen / state | Composable | In design system |
|---|---|---|---|
| 1 | Onboarding | `OnboardingScreen` | yes |
| 2 | Home — hero, chart, monitoring | `HeroPanel`, `RegistrationChart`, `MonitoringTile` | from parts only |
| 3 | Monitoring tab — three tiles | `ActionTile` ×3 | no |
| 4 | Checkpoint picker — country filters + list | `CheckpointPickerSheet`, `PickerRow` | no |
| 5 | Threshold dialog | `ThresholdChooserDialog` | no |
| 6 | Entry-time dialog | `EtaChooserDialog` | no |
| 7 | AI forecast dialog — three states | `ForecastDialog` | no |
| 8 | Remove-from-monitoring confirm | `ConfirmRemoveDialog` | no |
| 9 | Offline — two distinct states | `DataUnavailablePanel`, status pill | no |
| 10 | "Paused" badge in the list | `PauseBadge` | no |

Screen 7 has three states: `Завантаження…` → "model is still learning" with
progress → "expected queue peak". On real data only the second is visible today
— the model has collected 2 of 8 weeks.

Screen 9 is two different layouts: **offline with cache** (data stays, the pill
turns red) and **offline without cache** (full-screen "Дані недоступні" panel).

## Product frame

The app answers **when to act**, not "what the statistics are". The primary
message is the moment — "join now → entry 24.08 at 13:12"; the queue number and
the chart support that answer rather than being the point.

This is why server telemetry (load, memory, disk) was deliberately removed with
the old design: it is statistics that does not help decide when to drive.

## Open findings

Ranked. The first two are the ones that block a designer.

1. **The light theme is declared but does not work.** `Color.kt` defines a full
   light palette and `Theme.kt` switches on `isSystemInDarkTheme()`, but on a
   device in light mode both tabs stay dark — panel colours are hardcoded past
   the tokens. Verified on hardware. Either finish it or delete the light
   palette; the half-state is worse than both.
2. **Nine of ten screens are missing from the design system.** Until they exist,
   code is the only source of truth and every design change means reading
   Kotlin.
3. **Two visual languages.** Home is a photo hero with translucent "glass"
   cards; Monitoring is flat black with matte cards. One swipe apart, they read
   as two different apps.
4. **Three incompatible button/chip styles** — country filters (outlined pill),
   threshold chips (oval pill), "Закрити"/"Стежити" (solid yellow fill).
5. **No casing rule.** `АВТО В ЧЕРЗІ` and `СЕРВЕР ОНЛАЙН` sit beside
   `Динаміка реєстрацій` and `Ваш моніторинг`.
6. **Loading state has no design.** Fixed in code for issue #107, but with a
   placeholder spinner. A real waiting state — visually distinct from a
   genuinely empty one — is still missing.
7. **The monitoring section renders twice** — on Home and in the Monitoring tab.
8. **The `data` token is unused.** Blue `#0B5FA5` / `#4C97DB` is declared as the
   colour for data, but the chart draws in green `SignGo`. Either give charts
   the blue or drop the token.
9. **Checkpoint list states are unclear.** The pause icon appears on some rows
   and not others, with no visual explanation.

## Conventions

- **`Color.kt` wins over the HTML design system** when the two disagree.
- **Signal colours do not change between themes.** Only neutrals do.
- **A label must name its unit.** In a monitoring row the same label once sat
  above both a car count and an entry date; it is now `зараз, авто` and `в'їзд`.
- **Empty is not the same as not-yet-loaded.** Claiming "there is nothing" is
  only allowed after a successful server response. This was issue #107.
- **Checkpoints come from the backend.** No per-checkpoint logic in the UI. The
  owner's target crossings are Чоп (Тиса) – Захонь and Ужгород – Вишнє Нємецьке.

## Handoff document

A designer-facing version of this file, in Ukrainian and with colour swatches,
is published as an artifact:
<https://claude.ai/code/artifact/2ce39f8c-bc8c-4cfc-af00-ca08a1fe4c02>

It is private; the owner shares it from the page's share menu.

## History

The design reached `main` on 2026-08-20 through PR #106, which merged the
long-lived `feat/roadsign-design` branch (PR #94) and deleted the old Modernist
design in the same commit. Conflicts came from the i18n pass (#99), the only
commit on `main` that had touched the same UI files.

The APK that was on the device before that merge came from commit `e5ea3b8`,
kept reachable by the tag `apk/0.1.0-e5ea3b8` — a squash merge does not make the
original commit an ancestor of `main`.
