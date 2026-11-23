# Layouts

Write the source (`.slides.html`) as a list of `<section class="slide ...">` elements. The canvas is 1280×720px. Content may use the area inside the 80px side margins, down to y=620px (the strip below that is reserved for captions).

Any element can carry `data-say="narration"`; an element with it appears at the moment its narration is spoken. Components can be combined freely.

The example slides below are written in Japanese because that is the skill's main use. Write the on-screen text and narration in whatever language the user asked for.

## Contents

- [Cover `title`](#cover) / [Section divider `section`](#section-divider) / [Closing slide `end`](#closing-slide)
- [Heading and bullets (the basic slide)](#heading-and-bullets)
- [Cards in columns `cols` + `card`](#cards-in-columns)
- [Big number `stat`](#big-number)
- [Flow of steps `flow`](#flow-of-steps)
- [Table](#table) / [Big emoji `emoji-xl`](#big-emoji) / [Quote](#quote) / [Figures and images](#figures-and-images) / [Code](#code)
- [Small components](#small-components)
- [Entrance animations](#entrance-animations)
- [Changing colours](#changing-colours)

## Cover

```html
<section class="slide title">
  <p class="kicker">2026年度 新人研修</p>
  <h1 data-say="この動画では、経費精算のやり方を三分で説明します。">経費精算の<br>やり方</h1>
  <p class="sub" data-say="最後まで見れば、今日から自分で申請できます。">3分でわかる</p>
</section>
```

Keep the `h1` to two lines of about 12 full-width characters each.

## Section divider

Insert one where the topic changes. The background takes the accent colour.

```html
<section class="slide section">
  <p class="kicker">STEP 2</p>
  <h2 data-say="ここからは、申請の手順を見ていきましょう。">申請の手順</h2>
  <p class="sub">3つのステップ</p>
</section>
```

## Closing slide

```html
<section class="slide end">
  <h1 data-say="以上、経費精算のやり方でした。">まとめ</h1>
  <p class="sub" data-say="わからないことがあれば、経理チームまで気軽に聞いてください。">困ったら経理チームへ</p>
</section>
```

## Heading and bullets

The basic slide. `ul` gives round markers, `ol` gives numbers. Use 3 or 4 items of about 20 full-width characters each.

```html
<section class="slide">
  <h2 data-say="準備するものは三つです。">準備するもの</h2>
  <ul>
    <li data-say="一つ目は、領収書の写真。"><strong>領収書</strong>の写真</li>
    <li data-say="二つ目は、支払った日付と金額。">日付と金額</li>
    <li data-say="三つ目は、何のための支払いかというメモです。">目的のメモ</li>
  </ul>
</section>
```

For a small label above the heading, put `<p class="kicker">POINT 1</p>` before the `h2`.
Content is centred vertically by default. Use `class="slide top"` only when you want it aligned to the top.

## Cards in columns

For comparisons, categories and examples. Use 2 or 3 columns (text does not fit in 4).

```html
<section class="slide">
  <h2 data-say="申請方法は二つあります。">2つの申請方法</h2>
  <div class="cols">
    <div class="card" data-say="スマホアプリなら、撮影してそのまま申請できます。">
      <span class="emoji">📱</span><h3>アプリ</h3><p>撮ってすぐ申請</p>
    </div>
    <div class="card" data-say="パソコンからは、まとめて入力するのに向いています。">
      <span class="emoji">💻</span><h3>パソコン</h3><p>まとめて入力</p>
    </div>
  </div>
</section>
```

Keep the `p` inside a card to two lines. `.cols` also lays out things other than cards side by side (for example a list and a figure).
To change the column widths: `<div class="cols" style="grid-template-columns: 3fr 2fr; grid-auto-flow: row">`.

## Big number

Makes one number memorable. `data-anim="pop"` suits it. `tc` centres the slide horizontally as well.

```html
<section class="slide tc">
  <p class="kicker" data-say="次に、導入の効果です。">導入の効果</p>
  <p class="stat" data-anim="pop" data-say="申請にかかる時間は、七割減りました。">70<small>%減</small></p>
  <p class="big" data-say="月末の残業も、ほとんどなくなっています。">月末の残業が<mark>ほぼゼロ</mark>に</p>
</section>
```

For a time range or a longer figure, reduce the size a little so it stays on one line.

```html
<p class="stat" style="font-size:110px" data-anim="pop" data-say="コアタイムは、11時から15時です。">11:00<small>〜</small>15:00</p>
```

To show two or three numbers side by side, put `.card` elements in `.cols` and a `<p class="stat" style="font-size:96px">` in each.

## Flow of steps

Boxes in a row joined by arrows. Use 3 or 4 steps, at most two lines per box, with the detail in `<small>`.

```html
<section class="slide">
  <h2 data-say="申請は三つのステップで終わります。">申請の流れ</h2>
  <ol class="flow">
    <li data-say="まず、領収書を撮影します。">撮影する<small>アプリのカメラで</small></li>
    <li data-say="次に、金額と目的を入力します。">入力する<small>金額と目的</small></li>
    <li data-say="最後に、申請ボタンを押せば完了です。">申請する<small>ボタンを押すだけ</small></li>
  </ol>
</section>
```

## Table

Up to about 4 rows × 3 columns. Put one `data-say` on the whole table, or `<tr data-say="…">` to reveal it row by row.

```html
<section class="slide">
  <h2 data-say="プランは三種類です。">料金プラン</h2>
  <table>
    <thead><tr><th>プラン</th><th>月額</th><th>人数</th></tr></thead>
    <tbody>
      <tr data-say="個人向けのライトは、月額五百円。" data-caption="個人向けのライトは、月額500円。"><th>ライト</th><td>500円</td><td>1人</td></tr>
      <tr data-say="チーム向けのスタンダードは、月額三千円です。" data-caption="チーム向けのスタンダードは、月額3,000円です。"><th>スタンダード</th><td>3,000円</td><td>10人まで</td></tr>
    </tbody>
  </table>
</section>
```

## Big emoji

One emoji as the main visual in place of a figure. Combine it with `tc`.

```html
<section class="slide tc">
  <p class="emoji-xl" data-anim="pop" data-say="困ったときは、一人で抱え込まないでください。">🙋</p>
  <p class="big" data-say="人事部まで、気軽に相談してください。">困ったら<strong>人事部</strong>へ</p>
</section>
```

## Quote

```html
<section class="slide">
  <blockquote data-say="利用者からは、もう前のやり方には戻れない、という声が届いています。">もう前のやり方には<br>戻れません</blockquote>
  <p class="note" data-say>営業部 Aさん</p>
</section>
```

## Figures and images

Write `<img src="screen.png" alt="…">` using a path relative to the `.slides.html` file (or a data URI). `build.py` automatically embeds local PNG, JPEG, WebP, GIF, SVG and AVIF files as data URIs so the output stays a single self-contained HTML file (pass `--no-inline-images` to keep external links instead). Never use an external `http(s)://` URL. Always write `alt`.

`grow` on a `figure` makes it fill the remaining height. Add `class="frame"` to give a screenshot a subtle border and shadow.

```html
<section class="slide">
  <h2 data-say="画面はこのようになっています。">申請画面</h2>
  <figure class="grow" data-anim="zoom" data-say="上に金額、下に目的を入力する、シンプルな画面です。">
    <img class="frame" src="screen.png" alt="申請画面。上に金額欄、下に目的欄がある">
    <figcaption>申請画面</figcaption>
  </figure>
</section>
```

For text and an image side by side, put bullets and a `<figure>` inside `<div class="cols grow">`. Add `class="cover"` to crop a photo cleanly to fill its column, or place an `<img>` at the top of a `.card`.

```html
<section class="slide">
  <h2 data-say="アプリなら、撮るだけで申請が終わります。">アプリで完結</h2>
  <div class="cols grow">
    <ul>
      <li data-say="領収書をカメラで撮影します。">領収書を撮影</li>
      <li data-say="金額は自動で読み取られます。">金額を自動読み取り</li>
    </ul>
    <figure data-anim="zoom" data-say="確認ボタンを押せば申請完了です。">
      <img class="frame" src="app.png" alt="スマホアプリの撮影画面">
    </figure>
  </div>
</section>
```

For a full-bleed background photo on a cover, section or closing slide, put `<img class="bg" data-bleed src="hero.jpg" alt="">` inside the `<section>`. A dark scrim and white text are applied automatically.

```html
<section class="slide title">
  <img class="bg" data-bleed src="hero.jpg" alt="">
  <p class="kicker">2026年度 新人研修</p>
  <h1 data-say="この動画では、経費精算のやり方を三分で説明します。">経費精算のやり方</h1>
</section>
```

Draw simple diagrams as inline SVG. Use the theme variables for colours so the diagram matches the theme. Shapes inside the SVG (`path`, `rect`, or a `<g>` grouping several shapes) can carry `data-say` and appear in order.

```html
<figure class="grow">
  <svg viewBox="0 0 800 300" role="img" aria-label="AからBへデータが流れる図">
    <rect x="40" y="90" width="240" height="120" rx="20" fill="var(--card)" stroke="var(--accent)" stroke-width="4"/>
    <text x="160" y="162" text-anchor="middle" font-size="36" font-weight="800" fill="var(--fg)">アプリ</text>
    <path data-anim="fade" data-say="データは、アプリからサーバーへ送られます。" d="M300 150 H480" stroke="var(--accent)" stroke-width="8" marker-end="url(#arr)"/>
    <defs><marker id="arr" markerWidth="5" markerHeight="5" refX="2" refY="2.5" orient="auto"><path d="M0 0 L5 2.5 L0 5z" fill="var(--accent)"/></marker></defs>
    <rect x="520" y="90" width="240" height="120" rx="20" fill="var(--card)" stroke="var(--accent)" stroke-width="4"/>
    <text x="640" y="162" text-anchor="middle" font-size="36" font-weight="800" fill="var(--fg)">サーバー</text>
  </svg>
</figure>
```

Text inside an SVG must also render at 22px or more (the check measures it after the viewBox scaling). An element that is meant to extend past the slide area, such as a full-bleed background image, is exempt from the check when it has `data-bleed`.

## Code

Up to about 8 lines of 40 characters. Code is hard to read on a phone, so say the key point in the narration.

```html
<pre data-say="コマンドは一行だけです。"><code>npm install my-tool
my-tool start</code></pre>
```

## Small components

| Markup | Use |
|---|---|
| `<p class="kicker">` | small label above a heading |
| `<p class="big">` | larger body text (44px) |
| `<p class="note">` | supplementary note (26px, grey) |
| `<strong>` | emphasis in the accent colour |
| `<mark>` | highlighter underline |
| `<span class="badge">` | pill-shaped label |
| `<p class="emoji-xl">` | large emoji as the main visual |
| `<span class="emoji">` | emoji inside a card |
| `class="grow"` | fill the remaining height |
| `class="slide tc"` | centre horizontally too (when a number or emoji is the main visual) |
| `class="slide top"` | align content to the top (the default is vertical centring) |

## Entrance animations

Add `data-anim` to an element that has `data-say`.

| Value | Motion | Suits |
|---|---|---|
| (none) | rises in from below | bullets, cards |
| `fade` | appears in place | table rows, SVG lines |
| `zoom` | grows slightly | figures, images |
| `pop` | bounces in from small | numbers, emoji |
| `left` / `right` | slides in from the side | left/right comparisons |

The `li` or `.card` being narrated is highlighted automatically.

## Changing colours

Choose the scheme with `theme:` in the settings comment (the list is under "Themes" in SKILL.md). Only when none of the ten fits, add a `<style>` block to the source and override variables. `:root { … }` overrides them whichever theme is selected.

```html
<!--
title: 新サービスのご紹介
theme: light
-->
<style>
:root { --accent: #0f766e; --section-bg: #0f766e; --accent-soft: #d9f2ee; }
</style>
<section class="slide title"> … </section>
```

| Variable | Role |
|---|---|
| `--bg` / `--fg` / `--muted` | background, text, secondary text |
| `--accent` | main colour (emphasis, numbers, table header) |
| `--accent-2` | second colour (highlighter) |
| `--accent-soft` | pale accent (cover background) |
| `--card` / `--line` | card background and border |
| `--on-accent` | text on top of the accent colour |
| `--section-bg` / `--section-fg` | section-divider background and text |
| `--radius` / `--border-w` | card corner radius and border width |
| `--bar-w` / `--bar-color` | width and colour of the bar left of headings |
| `--deco-display` | decorative circles on the cover (`none` hides them) |
| `--font` / `--head-font` | body and heading fonts |

When you change colours, keep enough contrast between text and background (at least 4.5:1 for body text). Only fonts installed on the viewer's device can be used, so list candidates for both Windows and Mac / phones.
