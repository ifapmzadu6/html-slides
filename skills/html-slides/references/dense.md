# Information-dense business documents (density: dense)

How to write the kind of slide common in Japanese business: one slide that carries the conclusion, the evidence, the numbers and the source, as in meeting papers, reports, approval requests and comparisons of options. A finished example is `assets/starter-dense.slides.html` (6 slides).

## Contents

- [When to use it](#when-to-use-it)
- [Settings](#settings)
- [How to structure a slide](#how-to-structure-a-slide)
- [How much fits](#how-much-fits)
- [Narration](#narration)
- Components: [Conclusion line `lead`](#conclusion-line) / [Titled box `box`](#titled-box) / [Arrows between columns `arrows`](#arrows-between-columns) / [Stacking `rows`](#stacking) / [Nested bullets](#nested-bullets) / [Number table](#number-table) / [Comparison table `matrix`](#comparison-table) / [Schedule table `gantt`](#schedule-table) / [Label `tag`](#label) / [Source note `source`](#source-note) / [Footer](#footer)

## When to use it

| Use dense | Stay with the standard |
|---|---|
| reports to a management or regular meeting, approval requests, proposals, comparisons, plans | training, how-to, product introductions, announcements for a general audience |
| viewed on a computer or meeting-room screen, later handed out as a PDF | many viewers on phones |
| the user said "business document", "report", "pack in the detail", "like our PowerPoint reports" | nothing was specified |

A dense slide cannot be read on a phone held upright. If you do not know whether anyone will view it on a phone, tell the user about this limit.

## Settings

Add two lines to the settings comment of the source.

```html
<!--
title: 勤怠システム刷新 検討結果のご報告
theme: corporate
density: dense
footer: 社外秘 ｜ 情報システム部 ｜ 2026年11月
-->
```

- `density: dense` gives every slide except the cover, section dividers and the closing slide smaller type (22px body text) and tighter spacing, aligned to the top.
- `footer:` puts that text bottom-left and a page number bottom-right on every slide except the cover (also in the PDF). Write `footer:` with nothing after it for page numbers only. Only write a classification such as 社外秘 (confidential) or a department name if the user gave it to you; never add one yourself.
- To make only some slides dense, leave the setting out and write `<section class="slide dense">` on those slides.
- `corporate` or `light` are the safe themes.

## How to structure a slide

A business slide should give its conclusion to someone reading from the top.

1. **Heading `h2`**: what the slide is about (3案の比較).
2. **Conclusion line `lead`**: what the slide says (B案がもっとも優れる). Place it directly under the heading.
3. **Evidence**: boxes, a table or bullets, grouped into two or three blocks.
4. **Source or note `source`**: at the very bottom.

```html
<section class="slide">
  <h2 data-say="次に、三つの案の比較です。">3案の比較</h2>
  <p class="lead" data-say="総合評価では、B案がもっとも優れています。">機能・費用・導入期間のバランスで、B案がもっとも優れる</p>
  <table class="matrix"> … </table>
  <p class="source">※ 総費用は初期費用と5年分の利用料の合計（税抜）</p>
</section>
```

## How much fits

Dense does not mean unlimited. Past these amounts, split the slide in two (the check rejects overflow).

| Component | Fits on one slide |
|---|---|
| a slide of bullets only | 8-9 items (up to 40 full-width characters each) |
| one box, when three boxes sit side by side | 5 items (up to 14 characters each; at most 2 nested items) |
| table | 8 rows × 6 columns (not counting the header row) |
| table with two cards below it | table up to 5 rows |
| schedule table | 6 rows × 6-8 month columns |
| type size | under 14px fails the check; do not shrink text with `style` to make it fit |

Empty space at the bottom when there is little material is fine. **Never add content or numbers that were not in the material just to fill the space**; in a business document an unsupported statement is the worst outcome. To balance the look, put `grow` on the row of boxes or cards so it stretches, or merge two thin slides into one. Numbers you compute from the material (a difference, a percentage share) may be shown, but tell the user they are computed.

## Narration

Because the screen carries the detail, the narration **only points at the key points in order**. Do not read everything on screen.

- One sentence each on the heading and the `lead`. State the conclusion there.
- One sentence on each box (`box`), table row (`tr`) or card, so the blocks appear as they are discussed. Do not narrate individual bullets; it is too fine-grained and drags.
- To reveal a whole table at once, put one or two sentences on `<table data-say="…">`.
- Keep a slide to 30-40 seconds. If there is more to say, split the slide.
- Amounts and counts such as 4,800万円 or 1,200名 can be written as they are. Write phonetically, with `data-caption` for the spelling, only for long numbers mixing decimals with 億 / 万, Latin abbreviations and in-house terms.

## Conclusion line

```html
<p class="lead" data-say="結論から言うと、B案を提案します。">結論：クラウド型（B案）へ移行し、2027年4月に利用を開始する</p>
```

Keep it to one line (up to 40 full-width characters).

## Titled box

A named block, as in 現状 / 課題 / 対応策 (current state / issues / measures) or 背景 / 目的 / 効果 (background / purpose / effect). The `h3` becomes a coloured title band.

```html
<div class="box" data-say="現行システムは導入から12年がたっています。">
  <h3>現状</h3>
  <ul>
    <li>導入から12年が経過</li>
    <li>保守期限は2027年9月</li>
  </ul>
</div>
```

The body can be bullets, a `<p>` or a table.

## Arrows between columns

Adding `arrows` to `cols` draws an arrow between the columns. Adding `grow` stretches them over the remaining height.

```html
<div class="cols arrows grow">
  <div class="box" data-say="…"><h3>現状</h3> … </div>
  <div class="box" data-say="…"><h3>課題</h3> … </div>
  <div class="box" data-say="…"><h3>対応策</h3> … </div>
</div>
```

## Stacking

`rows` stacks several cards or boxes vertically inside one column of a `cols`. Use it for a table on the left with two number cards on the right.

```html
<div class="cols grow" style="grid-template-columns: 3fr 2fr; grid-auto-flow: row">
  <table> … </table>
  <div class="rows">
    <div class="card" data-say="…"><h3>集計作業の削減</h3><p class="stat">400<small>時間／年</small></p></div>
    <div class="card" data-say="…"><h3>コスト削減</h3><p class="stat">1,400<small>万円／5年</small></p></div>
  </div>
</div>
```

For a 2×2 grid, put four boxes in `<div class="cols" style="grid-template-columns: 1fr 1fr; grid-auto-flow: row">`.

## Nested bullets

A `ul` inside an `li` becomes a smaller sub-point. One level only.

```html
<ul>
  <li>法改正のたびに改修費が発生
    <ul><li>直近3年で計1,800万円</li></ul>
  </li>
</ul>
```

## Number table

`class="num"` right-aligns a numeric column. The total row is `<tr class="total">`. Row headings are `<th>`.

```html
<table data-say="5年間の合計は4,500万円です。">
  <thead><tr><th>費目</th><th class="num">初年度</th><th class="num">5年合計</th></tr></thead>
  <tbody>
    <tr><th>初期設定</th><td class="num">900万円</td><td class="num">900万円</td></tr>
    <tr><th>利用料</th><td class="num">720万円</td><td class="num">3,600万円</td></tr>
    <tr class="total"><th>合計</th><td class="num">1,620万円</td><td class="num">4,500万円</td></tr>
  </tbody>
</table>
```

## Comparison table

`class="matrix"` centres the cells. Add `ok` / `warn` / `ng` to a cell holding ○ / △ / × to colour it. Put a short remark under the mark with `<small>`.

```html
<table class="matrix">
  <thead><tr><th>評価項目</th><th>A案</th><th>B案</th><th>C案</th></tr></thead>
  <tbody>
    <tr data-say="スマホ打刻は、B案とC案で対応できます。"><th>スマホ打刻</th><td class="ng">×</td><td class="ok">○</td><td class="ok">○</td></tr>
    <tr data-say="法改正への対応は、B案だけが追加費用なしです。"><th>法改正への対応</th><td class="warn">△<small>都度改修</small></td><td class="ok">○<small>追加費用なし</small></td><td class="warn">△</td></tr>
    <tr class="total" data-say="以上から、B案を推奨します。"><th>総合評価</th><td class="warn">△</td><td class="ok">◎ 推奨</td><td class="ng">×</td></tr>
  </tbody>
</table>
```

Never rely on colour alone: always write the mark or a word as well.

## Schedule table

In a `class="gantt"` table, a task's period is a band: `<td class="bar" colspan="number of months">`. Months without a band are empty `<td></td>` cells. In every row, the `td` cells (counting each `colspan`) must add up to exactly the number of month columns. `bar alt` gives a band in the second colour.

```html
<table class="gantt">
  <thead><tr><th>作業</th><th>12月</th><th>1月</th><th>2月</th><th>3月</th></tr></thead>
  <tbody>
    <tr data-say="12月に契約します。"><th>契約</th><td class="bar">契約</td><td></td><td></td><td></td></tr>
    <tr data-say="1月から2月に設定と移行を進めます。"><th>設定・移行</th><td></td><td class="bar" colspan="2">設定・移行</td><td></td></tr>
    <tr data-say="3月に試験運用をおこないます。"><th>試験運用</th><td></td><td></td><td></td><td class="bar alt">試験</td></tr>
  </tbody>
</table>
```

## Label

A small outlined label for a status or category. `ok` / `warn` / `ng` change its colour.

```html
<h3><span class="tag warn">リスク</span> 年度末の繁忙期と重なる</h3>
<td><span class="tag ok">完了</span></td>
```

## Source note

Place it last on the slide. On a top-aligned slide it moves to the bottom edge by itself.

```html
<p class="source">出典：情報システム部 調べ（2026年10月時点）</p>
```

## Footer

Set once for the whole deck with `footer:` in the settings (see "Settings" above). Do not write it inside the slides.
