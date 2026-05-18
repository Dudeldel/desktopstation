# UI Designs

Mockupy wszystkich ekranów stacji 800×480px. Każdy plik HTML otwierany w przeglądarce pokaże renderowany widok zbliżony do tego co LVGL ma odtworzyć.

## Pliki

- [`00-all-screens.html`](00-all-screens.html) — wszystkie widoki na jednej stronie, do szybkiego skanowania
- [`01-screen-1-jira.html`](01-screen-1-jira.html) — ekran 1: Jira (moje + sprint + meetings)
- [`02-screen-2-messages.html`](02-screen-2-messages.html) — ekran 2: komunikacja
- [`03-screen-3-dev.html`](03-screen-3-dev.html) — ekran 3: dev (PR + CI + standup button)
- [`04-screen-4-todo.html`](04-screen-4-todo.html) — ekran 4: todo
- [`05-overlay-pomodoro.html`](05-overlay-pomodoro.html) — fullscreen pomodoro active
- [`06-overlay-break.html`](06-overlay-break.html) — fullscreen przerwa 5 min
- [`07-overlay-macros.html`](07-overlay-macros.html) — overlay makr 4×3

## Język wizualny

**Paleta:**
- Tło: `#0d0d10` (głębokie, nie czarne — łagodniej dla oczu w długim użyciu)
- Powierzchnia kart: `#16161a`
- Separatory: `#2a2a30`
- Tekst główny: `#e8e8ea`
- Tekst pomocniczy: `#8a8a90` / `#c8c8cc`

**Akcenty (kolor → znaczenie):**
- Zielony `#1d9e75` — akcje pozytywne, "mine", success
- Niebieski `#378add` — in progress, info
- Pomarańczowy `#ef9f27` — uwaga, running, "za chwilę"
- Różowy `#d4537e` — wymaga uwagi, unread badge, "ktoś czeka na ciebie"
- Czerwony `#e24b4a` — failed, high priority
- Fioletowy `#7f77dd` — AI/Claude, end of day, akcje meta

**Typografia:**
- Inter / Source Sans Pro (Latin Extended dla polskich znaków)
- Rozmiary: 36px (hero), 16px (heading), 13px (body), 11–12px (small), 9–10px (meta)
- Mono dla kodów: kluczy Jira, hashy branchy

**Rytmika:**
- Padding kart: 8–12px
- Gap między elementami listy: 4–6px
- Border radius: 6px (mały), 8px (karta), 50% (avatar)
- Top bar height: 40px
- Content height (pod paskiem): 440px

## Touch targets

Minimum 44×44px dla wszystkich interaktywnych elementów (Apple HIG). W praktyce:
- Wiersze list: 44–50px height
- Przyciski akcji: 32–48px height
- Checkboxy: 22×22px (ale z paddingiem wokół całego wiersza)
- Makra w gridzie: ~180×130px (luxus)

## Animacje

LVGL obsługuje out-of-the-box:
- Swipe lewo/prawo karuzeli: 300ms ease-out
- Fullscreen overlay entry: fade-in 200ms
- Checkbox toggle: scale + fade 150ms
- Toast: slide-from-top + fade 250ms in, hold 3s, fade-out

Bez przesadnych efektów — stacja to ma być narzędzie, nie pokazówka.

## Pasek górny — schemat

```
┌────────────────────────────────────────────────────────────────────┐
│ 14:23  pon, 18 maj                ☁ 18°  ✨42%▮▮▯  🍅3  [⚡ MAKRO]│
└────────────────────────────────────────────────────────────────────┘
```

5 segmentów: czas+data, pogoda, Claude usage, pomodoro counter, przycisk Makro.
Separatory pionowe 1px między grupami.

## Indykator karuzeli

```
                       ● ○ ○ ○        ← 4 kropki pod paskiem, aktywna jest podświetlona
```

Pozycja: top: 48px, left: 50%, transform: translateX(-50%). Małe (6×6px), nieinwazyjne.

## Co nie jest jeszcze zdesignowane

- **Toast** (małe powiadomienie u góry) — TBD w M2
- **Disconnected banner** — TBD w M2 (gdy daemon offline)
- **Loading state** — TBD; prawdopodobnie skeleton screen z szarymi placeholderami
- **Empty states** — TBD per ekran (np. "Brak nadchodzących spotkań", "Inbox zero!")
- **Error states** — TBD (np. Jira API down → pokaż cached + warning)

Te detale dochodzą w fazie M2 (UI scaffolding).
