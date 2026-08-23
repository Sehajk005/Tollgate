# Tollgate — UI/UX Design Specification

**Version:** v2.0 — 22 August 2026 (supersedes v1.0, 21 August)
**Companions:** PRD v2 · TRD v2 · Threat Model v2 · App Flow v2 · Eval Protocol v2 · Implementation Plan v2

---

## 0. The one-line brief

> Tollgate is instrumentation for money in motion. It should read like a well-made measuring device, not a security console.

Everything below derives from that sentence. Where a decision could go either way, the tiebreaker is: *does this look like an instrument, or does it look like a threat-intel product from a stock photo?*

### 0.1 What changed from v1

The visual system survives unchanged — colour discipline, the type pairing, spacing, elevation, motion, voice, and the Stream Rail all hold up and are kept as written. What changed is the **screen inventory the system serves**, plus three new component classes v1 had no reason to anticipate.

| Change | Why |
|---|---|
| Nav reduced to three items; D4/D5/D7/D8 components deleted | App Flow v2 §2 cut five dashboard screens |
| **New: system-state banner** (advisory mode, degraded mode) | v2 has states that are about *Tollgate's* health, not the store's threat level — and they must not look alike |
| **New: client-asserted evidence panel** | Threat Model v2 §2 requires unverified fields to be visibly untrusted |
| **New: proposed-vs-in-force** treatment on timeline and action bar | `block` / `step_up` are no longer automatic; a proposed action is a distinct object |
| Narrative block: pseudonyms, provenance label, 600-char cap, plain text | Threat Model v2 §5 — injection defence changes what the narrative may contain |
| Ticker and Stream Rail: `shed` and `fail_open` are distinct marks | TRD v2 §5.1 — an unscored attempt must not render as a confident tier |
| Contribution bars renamed from "SHAP" | LightGBM `pred_contrib` replaced the separate dependency |
| D6 gains dual-regime cost curves, a sensitivity ribbon, and audit bars | Eval Protocol v2 §1 — one cost curve became two plus a band |
| Replay chip copy rewritten | The virtual clock changed what that chip is claiming |
| Fonts via `@fontsource`, token-sheet page cut | Resolves a conflict with the Impl Plan's design-day budget |

---

## 1. Two products, two identities — and they must not match

*(Unchanged from v1. This was right.)*

The storefront and the dashboard are styled as if built by **two different companies**, because they were.

| | Storefront | Dashboard |
|---|---|---|
| Whose brand | The merchant's | Tollgate's |
| Polarity | Light | Dark |
| Density | Airy | Dense |
| Personality | Ordinary, trustworthy, forgettable | Precise, quiet, instrumented |
| Emotional job | "Nothing unusual is happening" | "Here is exactly what happened" |

If the storefront carries Tollgate's visual identity, the demo accidentally claims Tollgate takes over the merchant's brand — the opposite of the product's thesis. The storefront must look like *somebody else's shop*, one Tollgate is silently protecting.

**Kesar & Co.** — a small Indian D2C brand. Two products, honest photography, no design ambition. The forgettableness is functional: it makes Tollgate's invisibility legible.

---

## 2. Colour

### 2.1 The governing rules

**Indigo means interactive. Semantic colour means threat state. System health is monochrome. No two of these overlap.**

The first two rules are from v1 and stand. The third is new in v2 and it is load-bearing:

- **Indigo** — buttons, links, focus rings, active nav. Interactive affordances only. Never a state.
- **Amber / red / green** — **threat** state only. Never decoration, never a button, and — new — **never Tollgate's own health.**
- **Monitoring state is neutral grey, not blue.** "We are watching but nothing is wrong" is correctly expressed as the absence of colour.
- **System health — advisory mode, rules-only shedding, fail-open — renders monochrome**, on `--tg-surface-3` with a firm hairline and explicit copy. See §6.10.

That last rule matters more than it looks. v2 introduces states like *"enforcement paused, blast-radius cap reached"* and *"scorer unreachable, checkout proceeding unscored."* If those render amber, a judge sees amber and reads *"attack likelihood elevated"* when the actual meaning is *"our Redis is sad."* Colour on this dashboard makes exactly one claim: **how worried should you be about the store.** Never about the service.

Consequence, unchanged: on a calm store the dashboard is **entirely monochrome plus one indigo button**. When colour appears, it means something.

### 2.2 Dashboard tokens (dark)

```css
/* Surfaces — lightness is the elevation system */
--tg-canvas:        #0B0D10;
--tg-surface-1:     #12161B;
--tg-surface-2:     #191E25;
--tg-surface-3:     #212832;
--tg-hairline:      #262E38;
--tg-hairline-firm: #38424F;

/* Text */
--tg-text:          #F2F5F8;
--tg-text-2:        #A7B0BC;
--tg-text-mute:     #6E7885;

/* Interactive — indigo, and only indigo */
--tg-primary:       #6366F1;
--tg-primary-hover: #818CF8;
--tg-primary-press: #4F46E5;
--tg-primary-wash:  #6366F11F;
--tg-on-primary:    #FFFFFF;

/* Threat state — tuned for near-black, not borrowed from light-mode palettes */
--tg-calm:          #6E7885;   /* neutral. Deliberately not green. */
--tg-elevated:      #E3B341;
--tg-attack:        #F85149;
--tg-resolved:      #3FB950;

/* Threat washes — 10% fills */
--tg-elevated-wash: #E3B3411A;
--tg-attack-wash:   #F851491A;
--tg-resolved-wash: #3FB9501A;

/* NEW — system health. Monochrome by design. */
--tg-system-bg:     #212832;   /* = surface-3 */
--tg-system-edge:   #38424F;   /* = hairline-firm */
--tg-system-text:   #A7B0BC;
--tg-unverified:    #4A5460;   /* hatch/border for client-asserted data */
--tg-proposed:      #38424F;   /* dashed edge: exists, not in force */
```

**Why these semantic values and not `#22C55E / #EF4444 / #F59E0B`.** Those are tuned for white backgrounds. On `#0B0D10`, saturated mid-tone red and green vibrate against the background and fatigue the eye within a minute — a real problem for a screen someone leaves open all day. The values above sit in the range proven on dark developer surfaces. Substitute them and the dashboard looks subtly amateur in a way that's hard to diagnose.

**Calm is grey, not green.** A green "all clear" light trains the operator to look for colour, which means a calm store and a broken integration look equally green. Neutral calm makes amber genuinely alarming when it arrives.

### 2.3 Storefront tokens (light)

```css
--st-canvas:      #FFFFFF;
--st-canvas-soft: #F7F8FA;
--st-hairline:    #E4E8ED;
--st-ink:         #0D1520;
--st-ink-2:       #5A6674;
--st-ink-mute:    #8B96A3;
--st-action:      #111820;
--st-accent:      #1F6B4A;
--st-error:       #B42318;
```

Deep green rather than any accent from Tollgate's palette. It reads as ordinary retail trust, and it guarantees the two apps never look related.

### 2.4 Data-visualisation palette

Charts obey the same discipline. No categorical rainbow.

```css
--viz-series:     #A7B0BC;   /* the measured line — neutral */
--viz-baseline:   #38424F;   /* learned-baseline reference band */
--viz-threshold:  #6366F1;   /* the operating threshold marker */
--viz-attack:     #F85149;   /* attack-labelled regions only */
--viz-grid:       #1A2028;

/* NEW — for the dual-regime cost curves (Eval Protocol §1.4) */
--viz-series-alt: #A7B0BC;   /* SAME colour. Distinguished by dash, not hue. */
--viz-ribbon:     #A7B0BC14; /* 8% — the prevalence sensitivity band */
--viz-flag:       #E3B341;   /* discriminability audit: features above 0.95 AUC */
```

**The measured series is grey and the baseline band is greyer.** The story every chart tells is *departure from baseline*, not absolute value.

**The two cost curves share one colour and are separated by stroke, not hue** — steady-state solid, under-attack dashed, each labelled inline at its right terminus. Adding a second hue here would break the "colour means state" rule on the single most important chart in the deck. The dashed line reads as *"the same thing, under a different assumption,"* which is precisely the claim being made.

### 2.5 Accessibility floor

- Body text ≥ 4.5:1 against its surface. `--tg-text-mute` on `--tg-surface-1` is the tightest pair — verify it, use it only for non-essential text.
- **Colour is never load-bearing.** Every threat state carries a text label *and* a shape: calm = hollow ring, elevated = half-filled ring, attack = filled ring. A colourblind judge — roughly 1 in 12 men — must read the dashboard perfectly.
- New in v2: **every non-standard data provenance carries a shape too.** Unverified = hatched left edge. Proposed-not-in-force = dashed border. Shed/fail-open ticks = hollow. None of these rely on colour, because none of them *have* colour.
- Focus: 2px `--tg-primary` outline at 2px offset, on every interactive element. Never `outline: none`.

---

## 3. Typography

*(Unchanged from v1 except §3.5, which is new.)*

### 3.1 The pairing

**IBM Plex Sans** (UI, display) + **IBM Plex Mono** (all data).

A large share of every screen is *identifiers* — IPs, BINs, card hashes, decline codes, timestamps, latencies. Setting all of that in a mono face drawn as a sibling of the UI face makes the product read as instrumentation rather than a dashboard template. Plex also carries institutional weight without stiffness, which suits a payments-risk tool.

Deliberately not Inter (the default everything reaches for) and deliberately not Geist (reads as a Vercel tribute).

### 3.2 Thin weights don't survive the dark

On near-black surfaces, light-weight strokes bloom and lose definition at small sizes.

- **Dashboard:** minimum weight **400**. Display sizes **500–600**. Negative tracking only above 24px, gently (−0.2 to −0.5px, never −1.4px).
- **Storefront:** light polarity, so weight 300 is available for display sizes.

### 3.3 Dashboard scale

| Token | Size / LH | Weight | Tracking | Use |
|---|---|---|---|---|
| `display-lg` | 32 / 38 | 600 | −0.5px | Incident title, screen title |
| `display-md` | 24 / 30 | 600 | −0.3px | Section headers, metric tile values |
| `display-sm` | 20 / 26 | 500 | −0.2px | Card titles |
| `body-lg` | 16 / 26 | 400 | 0 | **The incident narrative.** Largest reading type on the page. |
| `body` | 14 / 20 | 400 | 0 | Default UI text |
| `body-strong` | 14 / 20 | 500 | 0 | Emphasis, active nav |
| `label` | 12 / 16 | 500 | 0.4px | Uppercase eyebrows, table headers |
| `caption` | 12 / 16 | 400 | 0 | Helper text, timestamps |
| `mono-data` | 13 / 18 | 400 | 0 | **Plex Mono.** IPs, BINs, hashes, decline codes, IDs |
| `mono-metric` | 28 / 32 | 500 | −0.3px | **Plex Mono, `tnum`.** Big numeric readouts |
| `mono-caption` | 11 / 14 | 400 | 0.3px | Latency badges, inline technical labels |

### 3.4 Tabular figures — non-negotiable

```css
.tg-num { font-variant-numeric: tabular-nums; font-feature-settings: "tnum"; }
```

Applied to **every** number that changes. Without it, live-updating digits jitter horizontally as they tick — on a real-time monitor that reads as instability in the thing being measured. One CSS line, and the single highest-leverage detail in this document.

### 3.5 Pseudonyms are data, and set as data — **new**

Threat Model v2 §5 requires the narrative to refer to entities as `ip_1`, `bin_A`, `card_7` rather than by their real values. Those pseudonyms set in **`mono-data`**, exactly as a real identifier would.

This is not a compromise, it is an improvement: `ip_1` in mono next to `203.0.113.4` in mono reads as *the same class of thing*, so the operator's eye moves between narrative and evidence table without friction. A pseudonym set in prose type would read as a placeholder and look unfinished.

---

## 4. Space, shape, elevation

*(Unchanged from v1.)*

### 4.1 Spacing

4px base: `4 · 8 · 12 · 16 · 24 · 32 · 48 · 64`.

- Dashboard section padding **24px**. Card interior **20px**. Table row height **44px**.
- Storefront section padding **64–96px**. The density contrast between the two apps should be obvious at a glance.

### 4.2 Radius — tighter than the reference material

| Token | Value | Use |
|---|---|---|
| `xs` | 4px | Chips, table cell chrome, mono tags |
| `sm` | 6px | Inputs, buttons, small controls |
| `md` | 8px | Cards, panels |
| `lg` | 12px | Modals, the incident detail panel |
| `pill` | 9999px | **Status badges only** |

Pills read consumer and marketing; an operational tool reads more credible with tight, near-square geometry. Reserving the pill exclusively for status badges makes those badges pop as a distinct object class — the only rounded thing on a screen of rectangles is the thing telling you how worried to be.

### 4.3 Elevation on dark — surfaces, not shadows

| Level | Treatment |
|---|---|
| 0 | `--tg-canvas` |
| 1 | `--tg-surface-1` + 1px `--tg-hairline` |
| 2 | `--tg-surface-2` + 1px `--tg-hairline` |
| 3 | `--tg-surface-3` + 1px `--tg-hairline-firm` |
| Overlay | `--tg-surface-2` + `--tg-hairline-firm` + `rgba(0,0,0,0.6)` scrim |

The storefront, being light, uses ordinary soft shadows. Same system, opposite physics.

---

## 5. The signature: the Stream Rail

**Every screen of the dashboard carries a 28px band directly under the top nav rendering the live authorisation stream as one 2px tick per scored attempt, scrolling right to left, coloured by decision tier.**

```
┌────────────────────────────────────────────────────────────────┐
│  TOLLGATE                        Live   Incidents   Metrics    │
├────────────────────────────────────────────────────────────────┤
│ ▏ ▏  ▏   ▏ ▏    ▏  ▏ ▏   ▏ ▏▏▏▏▍▍▍▍▍███████▍▍▍▏ ▏  ▏   ▏      │  ← Stream Rail
├────────────────────────────────────────────────────────────────┤
```

*(Nav updated: v1 showed Overview / Incidents / Analytics / Settings. Settings was D5, Analytics was D7/D8 — all cut.)*

Calm traffic is sparse, thin, neutral. An attack floods the rail — density climbs, ticks turn amber, then red — **before any counter moves and before the incident fires.** The operator sees the shape of the attack in their peripheral vision.

Why this and not a hero chart, a risk gauge, or a globe:

- It is the product's actual data used as ornament. Nothing is invented for decoration.
- It is honest about latency: the rail shows attempts arriving *before* detection concludes.
- On stage it is the moment the demo turns. A judge watching a counter increment feels nothing; a judge watching a calm rail suddenly go dense and red feels the attack.
- It costs roughly forty lines of canvas or SVG.

### 5.1 Two new tick marks — **new in v2**

TRD v2 §5.1 added a degraded rung between full scoring and fail-open. Those attempts were not fully scored, and **the rail must not render them as a confident tier**:

| Attempt | Mark |
|---|---|
| Fully scored | Solid 2px tick, tier-coloured |
| `shed` (rules-only) | **Hollow tick** — 2px outline, `--tg-text-mute`, no fill |
| `fail_open` | **A gap** — 2px of `--tg-canvas` with a 1px `--tg-system-edge` baseline stub |

This is the same honesty instinct that made the rail worth building, applied one level deeper. Under the Day-9 flood demo, the rail visibly changes texture from solid to hollow — the operator can *see* the system degrade gracefully rather than being told it did. It is the cheapest possible way to make the degraded-mode argument visual, and it is worth the twenty minutes.

**Restraint clause, unchanged:** the rail is the only ornamental element in the entire product. Spend the boldness here and nowhere else.

---

## 6. Components

### 6.1 Threat band (D1, full width)

```
┌────────────────────────────────────────────────────────────┐
│  ◉  UNDER ATTACK          Detected 38s ago   [View incident]│
│     Prior: under-attack regime · thresholds shifted         │
└────────────────────────────────────────────────────────────┘
```

Height 56px, or 72px when the regime line shows. Background = state wash. Left border 3px solid state colour. Ring glyph (hollow / half / filled) + uppercase `label` + description in `body`. Never colour alone.

States: `CALM` (neutral, no wash) · `ELEVATED` (amber) · `UNDER ATTACK` (red) · `RESOLVED` (green, auto-dismisses after 30s).

**The regime line is new**, and it is where the project's central idea becomes visible in one glance. When Layer 2 alarms, the serving prior moves from steady-state to under-attack and every tier threshold moves with it (Eval Protocol §1.2). Rendering that as a second line in `caption` — *"Prior: under-attack regime · thresholds shifted"* — means the Bayes argument is on screen during Act One rather than only on a slide during Act Two. It costs one line of markup.

### 6.2 Metric tile

```
┌──────────────────────┐   ┌──────────────────────┐
│ ATTEMPTS · 5 MIN     │   │ CARDS PER IP · TOP   │
│ 12,482               │   │ p99.4                │
│ ▲ 340% vs baseline   │   │ store baseline: p50  │
└──────────────────────┘   └──────────────────────┘
```

`--tg-surface-1`, 8px radius, 20px padding. **The delta line is the point** — an absolute number without its baseline comparison tells the operator nothing. Within the normal band, the delta renders in `--tg-text-mute` with no arrow.

Two of D1's four tiles changed shape in v2:

- **Distinct cards per IP is a quantile, not a count** (TRD §6.2 — the CGNAT fix). It renders as `p99.4` with the store's own baseline quantile beneath. A raw count here would be the exact thing the architecture spent effort removing: a number meaningless without knowing whether this store sits behind carrier-grade NAT.
- **Active enforcement renders as a fraction against the cap**: `7 / 10` with `caption` reading *"blast-radius cap"*. At `10 / 10` the tile's delta line switches to the system-state treatment, not a threat colour.

### 6.3 Status badge (the only pill)

Pill, 22px tall, `label` type, 8px horizontal padding. State wash background, state-coloured 1px border, state-coloured text. Always paired with its glyph.

**New variant — proposed:** dashed 1px `--tg-proposed` border, transparent fill, `--tg-text-2` text, glyph in outline. Used for a `block` or `step_up` that exists as a recommendation but has not been confirmed. See §6.6.

### 6.4 Event ticker row

```
10:14:22.113  ▏  ip_4 · 203.0.113…  411111  ₹1.00   0.87  CHALLENGE
10:14:22.140  ▏  ip_4 · 203.0.113…  411111  ₹1.00   —     SHED
10:14:22.171  ╎  —                  —       —       —     FAIL-OPEN
```

Single 28px row, `mono-data` throughout, `tnum` on every column. Left 2px tier stripe. Hover lifts to `--tg-surface-3`. New rows enter with a 120ms fade — **no slide**; at attack volume, sliding rows induce motion sickness.

Three v2 rules:

- **Pseudonym first, truncated real value second.** `ip_4 · 203.0.113…` — the pseudonym is what the narrative will call it, so the operator can cross-reference without a lookup. Click copies the full value.
- **Unscored rows show `—`, never a score.** A `shed` attempt has no model score and must not display one; a `fail_open` attempt has no decision at all. Rendering `0.00` there would be a lie in the most literal sense.
- Identifiers truncate to 8 characters. No PAN, email, or phone renders anywhere, ever.

### 6.5 Incident narrative block

`body-lg` at 16px — **the largest reading type in the product**, because the operator-owner persona reads this and nothing else.

Set on `--tg-surface-2`, 3px left border in the incident's state colour, 24px padding, max-width **68 characters**. Long measure is the most common way dashboards make prose unreadable.

**Four v2 requirements, all from Threat Model §5:**

1. **A provenance line above it**, in `label`, `--tg-text-mute`:
   `GENERATED SUMMARY · EVIDENCE BELOW IS AUTHORITATIVE`
2. **Entities appear as pseudonyms**, set in `mono-data` per §3.5.
3. **Plain text only.** No markdown rendering, no links, no HTML. 600-character cap with a hard truncation, not an ellipsis-expand.
4. **Template and LLM output render identically.** No badge distinguishing them, no layout shift when one falls back to the other. The `narrative_source` value is in the audit trail for anyone who asks; it is not a visual state, because the operator's trust should rest on the evidence below either way.

**The evidence-number treatment**, adapted from the keyword-highlight device in the Sentry reference: numbers inside the narrative that were decisive render in `mono-data` at `--tg-text`, one step brighter than the surrounding prose. Not highlighted, not boxed — typographically promoted.

> 47 attempts from `3` IP addresses (`ip_1`, `ip_2`, `ip_4`) against `2` card ranges in the last four minutes, all between `₹1` and `₹5`, `94%` declined for invalid CVV.

The prose stays readable; the evidence stays scannable. The mono face does the work a highlight colour would otherwise do, which keeps colour reserved for state.

**Note on §9's "no AI-powered in the UI" rule:** `GENERATED SUMMARY` is a provenance label, not a marketing claim, and it is required by the injection defence. It stays.

### 6.6 Detection timeline (D3)

Vertical rail, one node per tier transition, `mono-data` timestamps in a fixed-width left gutter.

```
10:14:01  ○  0.42   monitoring
10:14:10  ◐  0.62   THROTTLE       ← ─── CUSUM alert (λ ratio 6.2)
10:14:20  ◐  0.78   CHALLENGE            auto — ceiling reached
10:14:39  ◌  0.91   BLOCK  proposed      awaiting confirmation
```

*(v1's example showed BLOCK applied automatically at 10:14:39. Under v2 that is impossible — Threat Model §4/P1 caps automatic enforcement at `challenge`.)*

Three changes:

- **The detector is named at the alert point.** `CUSUM alert` or `distinct-card drift`, since v2 has two Layer 2 detectors and which one fired is genuinely informative — CUSUM catches bursts, drift catches low-and-slow.
- **The ceiling is annotated.** `auto — ceiling reached` on the `challenge` node makes the security posture legible without a paragraph.
- **Proposed nodes use a dotted glyph `◌` and a dashed connector**, and sit at reduced opacity until confirmed. On confirmation the glyph fills and the connector goes solid — a 400ms transition, one of the two moments in the product given real duration.

**This remains the most defensible visual in the product.** It shows detection as a progression with a marked decision point rather than a magic verdict — and in v2 it also shows where the machine stopped and asked a human, which is a stronger claim than automation would have been.

### 6.7 Contribution bars

*(Renamed from "SHAP" — v2 uses LightGBM `pred_contrib`, and the acronym was never operator-facing language anyway.)*

Horizontal bars, `--tg-text-2` fill on `--tg-surface-2` track, feature name in `body` left, value in `mono-data` right. Top 3 only.

Grey, not indigo — these are measurements, not actions. The moment they're brand-coloured they start looking like progress bars.

Feature names render in operator language, not code identifiers: *"Distinct cards from this IP (5 min)"*, not `distinct_cards_per_ip_5m_q`. The mapping lives in one dictionary beside the feature list.

### 6.8 Entity table

Plex Mono throughout with `tnum`. 44px rows, 1px `--tg-hairline` dividers, header in `label` on `--tg-surface-2`. Right-align numerics. Row hover `--tg-surface-3`. Sortable columns show direction with a caret in `--tg-text-mute`.

**Pseudonym column first**, then the real key truncated, then counts. This table is the narrative's decoder ring, so the pseudonym has to be the leftmost thing the eye lands on.

Entity type renders explicitly — `ip`, `ip+ua`, `bin`, `card` — because v2's composite keys mean *"which entity"* is no longer obvious. An operator seeing enforcement on `ip+ua` rather than `ip` should be able to see that it's narrower.

### 6.9 Client-asserted evidence panel — **new**

Collapsed by default, below the entity table on D3.

```
┌─ CLIENT-ASSERTED · UNVERIFIED · NOT USED IN SCORING ────────┐
│▨ user agent      Mozilla/5.0 (X11; Linux x86_64)…           │
│▨ device id       dev_7c1e…                                  │
│▨ checkout path   /checkout                                  │
│▨ time on site    1,240 ms                                   │
└─────────────────────────────────────────────────────────────┘
```

- Header in `label`, `--tg-text-mute`, and it says all three things: unverified, client-asserted, unused.
- **A 3px hatched left edge** in `--tg-unverified` — a texture no other panel uses, so the untrusted class is recognisable without reading.
- Values in `mono-data` at `--tg-text-2`, one step down from real evidence. `user_agent` is truncated at 60 characters and never rendered as anything but inert text.
- Panel is not sortable, not filterable, not linkable. It is a record, not an instrument.

This panel exists to make the trust boundary *visible*. A judge looking for the security answer will find it here in three seconds, and — the reason it earns its place in the build — it makes quietly promoting one of these fields into the model later an awkward, obvious act rather than a two-line change nobody notices.

### 6.10 System-state banner — **new**

Full-width, directly under the Stream Rail, only when active. `--tg-system-bg`, 1px `--tg-system-edge`, no wash, no state colour, no glyph fill — a horizontal `⌁` mark in `--tg-text-mute`.

```
┌─────────────────────────────────────────────────────────────┐
│ ⌁  Enforcement paused — blast-radius cap reached (10 / 10). │
│    Scoring continues. Resolve incidents to resume.          │
└─────────────────────────────────────────────────────────────┘
```

Three variants, all monochrome:

| Variant | Copy |
|---|---|
| **Advisory mode** | "Enforcement paused — blast-radius cap reached (10 / 10). Scoring continues. Resolve incidents to resume." |
| **Rules-only** | "Rules-only scoring — request rate above budget. 1,204 attempts scored on rules in the last minute." |
| **Fail-open** | "Scorer unreachable for 40s. Checkout is unaffected — attempts are passing through unscored. Check the service on port 8080." |

Stacks below the threat band when both are showing, and **never above it**: the store's threat level outranks Tollgate's health, always. Dismissible only by the condition clearing.

The fail-open copy is lifted verbatim from v1's §8 voice example, which was already exactly right — it just had no component to live in.

### 6.11 Buttons

| Variant | Fill | Text | Border |
|---|---|---|---|
| Primary | `--tg-primary` | `--tg-on-primary` | none |
| Secondary | transparent | `--tg-text` | 1px `--tg-hairline-firm` |
| Ghost | transparent | `--tg-text-2` | none |
| Destructive | transparent | `--tg-attack` | 1px `--tg-attack` |

32px (compact) / 40px (default). 6px radius. **One primary button per screen region.**

**New — the confirm-with-consequence pattern.** Because `block` and `step_up` require a human, their button carries the cost inline rather than opening a modal:

```
┌──────────────────────────────────────┐
│  Confirm block · 2 entities          │
│  Est. cost if wrong: ₹720            │  ← caption, --tg-text-mute
└──────────────────────────────────────┘
```

Destructive variant. The cost line comes straight from `C_FP(block) × entity count` in the cost model (Eval Protocol §1.3), so the operator is shown the same arithmetic the thresholds were derived from at the exact moment they overrule it. No modal, no "are you sure" — a number is a better confirmation dialogue than a question.

### 6.12 Demo control strip

`--tg-surface-2`, pinned bottom, 1px top hairline, 56px tall. Controls in `label` type. Tier selector now carries four options — easy / medium / hard / **evasive**. Two separate degradation toggles, **flood** and **kill scorer**, because they demonstrate two different rungs.

The replay chip is a persistent `mono-caption`, and its copy changed:

```
  ×60 VIRTUAL CLOCK · WINDOWS PRESERVED · TTD IN EVENT TIME
```

v1's chip read `REPLAY ×60`, which honestly flagged a real problem — at 60× the windows compressed too, so demo detection wasn't production detection. v2 fixed the underlying issue with an injected clock (TRD §4), so the chip now states the fix rather than confessing the flaw. It still never hides and never dims. Its permanence is the point; what changed is that it now works in your favour.

### 6.13 D6 metric blocks — **new detail**

Six blocks (App Flow §5). Three need specification beyond ordinary charts:

**Per-tier performance** — grouped horizontal bars, `recall @ FPR 1e-3` per tier, `--viz-series` fill. The evasive tier's bar is the shortest and gets **no special treatment at all**: no red, no warning icon, no apology. It is simply the fourth bar, labelled, at whatever height it is. Dressing it up would undercut the reason it is there.

**Discriminability audit** — horizontal bars of univariate AUC per feature, sorted descending, with a `--viz-threshold` rule at 0.95. Any bar crossing it renders in `--viz-flag` amber with a `label` annotation reading `FLAGGED — GENERATOR ARTIFACT`. This is the only place in the product where amber does not mean threat state, and it is justified: the flag means *this measurement is suspect*, which is the closest thing a chart has to an alarm.

**Cost curves** — two lines, same colour, solid = steady state, dashed = under attack, each labelled inline at its right terminus. `--viz-ribbon` fill for the prevalence sensitivity band. Two `--viz-threshold` markers with `mono-caption` callouts: `F1-optimal` and `cost-optimal`, with the rupee gap set between them in `mono-metric`. Both regimes' π values are printed on the axis label, not in a caption — a curve whose prevalence you have to hunt for is how v1's number became arbitrary in the first place.

---

## 7. Motion

*(Unchanged, plus one row.)*

| Element | Treatment |
|---|---|
| Ticker rows | 120ms fade-in. No slide. |
| Stream Rail | Continuous scroll, `requestAnimationFrame`, no easing |
| Metric counters | 200ms count-up, `tnum` prevents reflow |
| **Threat band state change** | **400ms** — wash fades, left border expands 0→3px, glyph fills |
| **Proposed → confirmed** *(new)* | **400ms** — dashed border solidifies, glyph fills, opacity 0.6→1 |
| System-state banner | 150ms opacity. Never animated in colour — it has none. |
| Panel/route transitions | 150ms opacity only |
| Hover | 100ms background only |

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important; }
}
```

The Stream Rail switches to a static snapshot under reduced motion.

Two moments now get real duration instead of one — the threat band changing, and a human confirming an enforcement action. Both are moments where something irreversible happens, which is the only justification for spending 400ms.

---

## 8. Voice

**Plain and specific over technical or dramatic.**
- ✅ "47 attempts from 3 IP addresses in the last 4 minutes."
- ❌ "Anomalous velocity signature detected across entity cluster."
- ❌ "🚨 THREAT NEUTRALIZED"

**Name things by what the operator controls.** "Response level," not "policy tier enum." "Card ranges," not "BIN space." "Cards exposed," not "`cards_exposed_before_alert`."

**Actions keep their name through the flow.** *Apply response* → *Response applied* → audit row *Response applied*.

**Empty states are evidence, not apology.**
> No incidents. Baseline learned from 4,210 attempts over 6 days.

**Errors say what happened and what to do. They don't apologise.**
> Scorer unreachable for 40s. Checkout is unaffected — attempts are passing through unscored. Check the service on port 8080.

**Hedge when the evidence hedges.** When BIN concentration is low and IP diversity is high, the narrative should say *may be a legitimate traffic surge*. A system that cries attack every time gets switched off in week one.

**New — say what a number is conditional on.** v2's central correction was that a metric without its conditions is meaningless, and the copy has to carry that or the fix stops at the code.
- ✅ "₹4,200 saved per 10,000 attempts, at steady-state prevalence."
- ❌ "₹4,200 saved per 10,000 attempts."
- ✅ "Detected after 47 attempts, 43 cards exposed."
- ❌ "Detected in 38 seconds." *(true, but it's the attacker's pacing, not our sensitivity)*

**New — never describe unverified data as if it were observed.** *"Client reported a 1,240 ms session"*, not *"Session lasted 1,240 ms."* The verb carries the trust boundary.

---

## 9. What this product does not do

Explicitly forbidden, because every one appears in the security-dashboard genre and every one would cost credibility with a payments audience:

Glowing globes · circular risk gauges · matrix rain · hexagonal grids · neon glow or `box-shadow` bloom · gradient-filled cards · animated particle backgrounds · shield or padlock iconography · skull imagery · "AI-powered" anywhere in the UI · more than one accent hue · emoji as state indicators · dark-mode charts with rainbow categorical series · progress rings for anything that isn't progress · glassmorphism.

**Added in v2:** no confidence percentages on the narrative ("94% confident this is an attack" invites a question the narrator cannot answer — the calibrated probability lives on the attempt, not the prose) · no threat colour on anything describing Tollgate's own health · no score shown for an attempt that wasn't scored.

The rule underneath: **Tollgate looks like a Bloomberg terminal built by someone with taste, not like a movie hacker's screen.** Its audience sells kurtas and cares about auth rates.

---

## 10. Implementation

Tailwind, tokens in `tailwind.config.js` mapped to the CSS variables above. Two theme scopes — `.tg-app` (dark) and `.st-app` (light) — so no component ever guesses its polarity.

```
services/dashboard/src/styles/
├── tokens.css        # all CSS variables, both scopes
├── type.css          # font imports, scale utilities, .tg-num
└── base.css          # reset, focus ring, reduced-motion
```

**Fonts: `@fontsource/ibm-plex-sans` (400/500/600) and `@fontsource/ibm-plex-mono` (400/500), via npm.**

This resolves a conflict between v1 of this document and the v2 Implementation Plan. v1 specified self-hosted woff2 subsets; the Impl Plan cut "self-hosted font subsets" as part of a 1.0-day design saving. Both were half right. **Self-hosting is non-negotiable** — the demo must render with no network, and a font falling back to system-ui mid-pitch visibly breaks every alignment in the tables. But *hand-subsetting* was the expensive part, and `@fontsource` gives self-hosted woff2 for two npm installs and one import line. Keep the property, drop the labour. What actually stays cut is the **token-sheet page** — a screen no judge will see.

### Build sequence — mapped to Implementation Plan v2 days

| Day | UI work | Budget |
|---|---|---|
| **1** | Ugly S2 checkout + D1 ticker. **No tokens, no polish** — this is the walking skeleton, and it exists to prove the pipe works. **v2.1 — explicit exclusion list:** no Tailwind, no design tokens, no router, no component library, no state-management framework, no animation system. Two Vite + React 18 apps, one `App.jsx` each, plain `fetch()` + `EventSource`, a Vite dev-server proxy between them. | ~2h |
| **2** | D1 threat band + four metric tiles + DC strip, unstyled. Act One demonstrable. | ~2h |
| **8** | `tokens.css` + `type.css` → Stream Rail → threat band → metric tile → ticker row → narrative block → timeline → contribution bars → tables → D6 charts | **1h tokens (hard cap)** + ~6h components |
| **9** | Storefront scope, deliberately plain | **3h maximum** |

The reordering from v1 matters. v1 built design tokens in Phase 11 (Day 6 evening) before any component existed, which is the correct order in a normal project and the wrong order here: it front-loads polish ahead of the integration risk. In v2 the ugly version of every screen exists by Day 2 and the styling pass lands on Day 8 against components that already work.

**Check Plex Mono at 13px in a realistic table row on Day 1**, not Day 8 — the ticker is built on Day 1 and it is the first place the mono face appears at density. If it runs wide, fall back to Inter then, when it costs nothing.

---

## 11. Open decisions

| # | Decision | Recommendation |
|---|---|---|
| 1 | Plex vs. Inter | **Plex.** Distinct, and the mono sibling carries the data layer. Check at 13px on **Day 1** — Inter is the no-cost fallback. |
| 2 | Stream Rail on every screen, or D1 only | **Every screen.** With only four screens left it is what stops the app feeling like separate pages. |
| 3 | Storefront light vs. dark | **Light, firmly.** The polarity contrast is what makes the split-screen demo legible at a glance. |
| 4 | Indigo `#6366F1` vs. a payments-blue | Indigo. Blue collides with the "monitoring" reading. |
| 5 | **New —** Regime line on the threat band, or leave it to D6 | **On the band.** The prior moving is the thesis; showing it during Act One is worth one line of markup. |
| 6 | **New —** Client-asserted panel expanded or collapsed by default | **Collapsed.** Expanded, it competes with real evidence; collapsed with an explicit header, it reads as deliberate scoping — which it is. |
