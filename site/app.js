// marketlens-sql showcase.
// Reads the JSON snapshot produced by scripts/export_site_data.py and draws
// every chart as plain SVG or HTML. No metric is calculated here: all values
// come from the SQL queries. The plain-language summaries under each chart
// only pick out the highest and lowest of those values.

"use strict";

const DATA_DIR = "data";
const SERIES_COLOURS = 6;
const SVG_NS = "http://www.w3.org/2000/svg";

const state = {
  meta: null,
  periodKey: "1y",
  windowKey: "volatility_20d",
  hidden: new Set(),
  periods: {},
};

// Formatting -------------------------------------------------------------

function formatPercent(value, digits = 1) {
  if (value === null || value === undefined) return "–";
  const sign = value > 0 ? "+" : "";
  return `${sign}${(value * 100).toFixed(digits)}%`;
}

function formatPercentPlain(value, digits = 0) {
  return `${(value * 100).toFixed(digits)}%`;
}

const dateFormatter = new Intl.DateTimeFormat("en-GB", {
  day: "numeric", month: "short", year: "numeric", timeZone: "UTC",
});
const monthFormatter = new Intl.DateTimeFormat("en-US", {
  month: "short", year: "2-digit", timeZone: "UTC",
});

function formatDate(isoDate) {
  if (!isoDate) return "–";
  return dateFormatter.format(new Date(`${isoDate}T00:00:00Z`));
}

// Assets -------------------------------------------------------------------

function assetLabel(asset) {
  // Index tickers such as ^GSPC are not meaningful to most readers.
  return asset.asset_type === "index" ? asset.name : asset.ticker;
}

function assetColour(ticker) {
  const asset = state.meta.assets.find((item) => item.ticker === ticker);
  if (asset.asset_type === "index") return "var(--series-benchmark)";
  const others = state.meta.assets.filter((item) => item.asset_type !== "index");
  const position = others.findIndex((item) => item.ticker === ticker);
  return `var(--series-${(position % SERIES_COLOURS) + 1})`;
}

function visibleAssets() {
  return state.meta.assets.filter((asset) => !state.hidden.has(asset.ticker));
}

function labelFor(ticker) {
  return assetLabel(state.meta.assets.find((asset) => asset.ticker === ticker));
}

// SVG helpers --------------------------------------------------------------

function svgElement(name, attributes = {}) {
  const element = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attributes)) {
    element.setAttribute(key, value);
  }
  return element;
}

function niceStep(range, targetTicks) {
  const rough = range / targetTicks;
  const magnitude = 10 ** Math.floor(Math.log10(rough));
  const residual = rough / magnitude;
  const factor = residual > 5 ? 10 : residual > 2 ? 5 : residual > 1 ? 2 : 1;
  return factor * magnitude;
}

function valueTicks(min, max, targetTicks) {
  const step = niceStep(max - min || 1, targetTicks);
  const ticks = [];
  for (let tick = Math.ceil(min / step) * step; tick <= max + step * 1e-9; tick += step) {
    ticks.push(Math.abs(tick) < step * 1e-9 ? 0 : tick);
  }
  return ticks;
}

function timeTicks(startMs, endMs, maxTicks) {
  // First day of a month, spaced by the smallest step that fits.
  const spanMonths = (endMs - startMs) / (30.44 * 86400000);
  const step = [1, 2, 3, 6, 12, 24].find((months) => spanMonths / months <= maxTicks) || 24;
  const start = new Date(startMs);
  let year = start.getUTCFullYear();
  let month = start.getUTCMonth() + 1;
  const ticks = [];
  for (;;) {
    if (month > 11) { year += Math.floor(month / 12); month %= 12; }
    const tick = Date.UTC(year, month, 1);
    if (tick > endMs) break;
    if (step < 12 ? month % step === 0 : month === 0 && year % (step / 12) === 0) ticks.push(tick);
    month += 1;
  }
  return { ticks, yearly: step >= 12 };
}

// Line chart -------------------------------------------------------------

function nearestIndex(points, targetMs) {
  let low = 0;
  let high = points.length - 1;
  while (low < high) {
    const middle = (low + high) >> 1;
    if (points[middle].t < targetMs) low = middle + 1; else high = middle;
  }
  if (low > 0 && Math.abs(points[low - 1].t - targetMs) < Math.abs(points[low].t - targetMs)) {
    return low - 1;
  }
  return low;
}

function drawLineChart(container, seriesByTicker, options) {
  container.replaceChildren();
  const tickers = visibleAssets().map((asset) => asset.ticker).filter((t) => seriesByTicker[t]);
  if (tickers.length === 0) {
    container.append(statusMessage("Select at least one asset."));
    return;
  }

  const series = tickers.map((ticker) => ({
    ticker,
    points: seriesByTicker[ticker].map(([date, value]) => ({
      t: Date.parse(`${date}T00:00:00Z`), date, value,
    })),
  }));

  const width = container.clientWidth;
  const height = width < 560 ? 240 : 320;
  const margin = { top: 12, right: 12, bottom: 28, left: 52 };
  const innerWidth = width - margin.left - margin.right;
  const innerHeight = height - margin.top - margin.bottom;

  let minT = Infinity; let maxT = -Infinity; let minV = Infinity; let maxV = -Infinity;
  for (const { points } of series) {
    for (const point of points) {
      minT = Math.min(minT, point.t); maxT = Math.max(maxT, point.t);
      minV = Math.min(minV, point.value); maxV = Math.max(maxV, point.value);
    }
  }
  if (options.includeZero) { minV = Math.min(minV, 0); maxV = Math.max(maxV, 0); }
  const padding = (maxV - minV) * 0.05 || 0.01;
  minV -= padding; maxV += padding;

  const x = (t) => margin.left + ((t - minT) / (maxT - minT || 1)) * innerWidth;
  const y = (v) => margin.top + (1 - (v - minV) / (maxV - minV)) * innerHeight;

  const svg = svgElement("svg", {
    viewBox: `0 0 ${width} ${height}`,
    height,
    role: "img",
    "aria-label": options.label,
  });

  const axis = svgElement("g", { class: "axis" });
  for (const tick of valueTicks(minV, maxV, height < 300 ? 4 : 6)) {
    axis.append(svgElement("line", {
      class: tick === 0 ? "zero-line" : "gridline",
      x1: margin.left, x2: width - margin.right, y1: y(tick), y2: y(tick),
    }));
    const label = svgElement("text", { x: margin.left - 8, y: y(tick) + 4, "text-anchor": "end" });
    label.textContent = formatPercentPlain(tick, Math.abs(tick) < 0.1 && tick !== 0 ? 1 : 0);
    axis.append(label);
  }
  const { ticks, yearly } = timeTicks(minT, maxT, width < 560 ? 4 : 7);
  for (const tick of ticks) {
    const label = svgElement("text", { x: x(tick), y: height - 6, "text-anchor": "middle" });
    label.textContent = yearly ? new Date(tick).getUTCFullYear() : monthFormatter.format(new Date(tick));
    axis.append(label);
  }
  svg.append(axis);

  for (const { ticker, points } of series) {
    const path = points
      .map((point, index) => `${index ? "L" : "M"}${x(point.t).toFixed(1)},${y(point.value).toFixed(1)}`)
      .join("");
    svg.append(svgElement("path", {
      d: path,
      fill: "none",
      style: `stroke: ${assetColour(ticker)}`,
      "stroke-width": 1.6,
      "stroke-linejoin": "round",
    }));
  }

  // Hover: a vertical rule, one dot per series and a tooltip.
  const rule = svgElement("line", {
    class: "hover-rule", y1: margin.top, y2: height - margin.bottom, visibility: "hidden",
  });
  const dots = series.map(({ ticker }) => svgElement("circle", {
    r: 3.5, style: `fill: ${assetColour(ticker)}`, visibility: "hidden",
  }));
  svg.append(rule, ...dots);

  const overlay = svgElement("rect", {
    x: margin.left, y: margin.top, width: innerWidth, height: innerHeight, fill: "transparent",
  });
  svg.append(overlay);

  const tooltip = document.createElement("div");
  tooltip.className = "tooltip";
  tooltip.hidden = true;

  function showAt(clientX) {
    const bounds = svg.getBoundingClientRect();
    const scale = width / bounds.width;
    const pointerX = (clientX - bounds.left) * scale;
    const targetT = minT + ((pointerX - margin.left) / innerWidth) * (maxT - minT);

    const rows = [];
    let ruleT = null;
    series.forEach(({ ticker, points }, index) => {
      const point = points[nearestIndex(points, targetT)];
      ruleT = ruleT ?? point.t;
      dots[index].setAttribute("cx", x(point.t));
      dots[index].setAttribute("cy", y(point.value));
      dots[index].setAttribute("visibility", "visible");
      rows.push({ ticker, value: point.value, date: point.date });
    });
    rule.setAttribute("x1", x(ruleT));
    rule.setAttribute("x2", x(ruleT));
    rule.setAttribute("visibility", "visible");

    rows.sort((a, b) => b.value - a.value);
    tooltip.replaceChildren();
    const dateLine = document.createElement("div");
    dateLine.className = "tooltip-date";
    dateLine.textContent = formatDate(rows[0].date);
    tooltip.append(dateLine);
    for (const row of rows) {
      const line = document.createElement("div");
      line.className = "tooltip-row";
      line.innerHTML = `<span class="swatch" style="background:${assetColour(row.ticker)}"></span>`
        + `<span></span><span></span>`;
      line.children[1].textContent = labelFor(row.ticker);
      line.children[2].textContent = options.format(row.value);
      tooltip.append(line);
    }
    tooltip.hidden = false;
    const left = (x(ruleT) / scale) + 12;
    const flip = left + tooltip.offsetWidth > bounds.width;
    tooltip.style.left = `${flip ? left - tooltip.offsetWidth - 24 : left}px`;
  }

  function hide() {
    rule.setAttribute("visibility", "hidden");
    dots.forEach((dot) => dot.setAttribute("visibility", "hidden"));
    tooltip.hidden = true;
  }

  overlay.addEventListener("pointermove", (event) => showAt(event.clientX));
  overlay.addEventListener("pointerdown", (event) => showAt(event.clientX));
  overlay.addEventListener("pointerleave", hide);

  container.append(svg, tooltip);
}

// Scatter: return against volatility --------------------------------------

function drawScatter(container, rows) {
  container.replaceChildren();
  const points = rows.filter((row) => row.annualised_volatility !== null && row.annualised_return !== null);
  if (points.length === 0) {
    container.append(statusMessage("Select at least one asset."));
    return;
  }

  const width = container.clientWidth;
  const height = 260;
  const margin = { top: 24, right: 64, bottom: 44, left: 52 };
  const innerWidth = width - margin.left - margin.right;
  const innerHeight = height - margin.top - margin.bottom;

  const maxX = Math.max(...points.map((p) => p.annualised_volatility)) * 1.1;
  let minY = Math.min(0, ...points.map((p) => p.annualised_return));
  let maxY = Math.max(0, ...points.map((p) => p.annualised_return));
  const padding = (maxY - minY) * 0.1 || 0.05;
  minY -= padding; maxY += padding;

  const x = (v) => margin.left + (v / maxX) * innerWidth;
  const y = (v) => margin.top + (1 - (v - minY) / (maxY - minY)) * innerHeight;

  const svg = svgElement("svg", {
    viewBox: `0 0 ${width} ${height}`, height, role: "img",
    "aria-label": "Annualised return against annualised volatility",
  });
  const axis = svgElement("g", { class: "axis" });
  for (const tick of valueTicks(minY, maxY, 4)) {
    axis.append(svgElement("line", {
      class: tick === 0 ? "zero-line" : "gridline",
      x1: margin.left, x2: width - margin.right, y1: y(tick), y2: y(tick),
    }));
    const label = svgElement("text", { x: margin.left - 8, y: y(tick) + 4, "text-anchor": "end" });
    label.textContent = formatPercentPlain(tick);
    axis.append(label);
  }
  for (const tick of valueTicks(0, maxX, 4)) {
    const label = svgElement("text", { x: x(tick), y: height - 16, "text-anchor": "middle" });
    label.textContent = formatPercentPlain(tick);
    axis.append(label);
  }
  const xTitle = svgElement("text", { x: margin.left + innerWidth, y: height - 2, "text-anchor": "end" });
  xTitle.textContent = "Volatility →";
  const yTitle = svgElement("text", { x: margin.left - 8, y: 10, "text-anchor": "end" });
  yTitle.textContent = "Return ↑";
  axis.append(xTitle, yTitle);
  svg.append(axis);

  // Labels of nearby points are pushed apart vertically so they stay legible.
  const LABEL_HEIGHT = 14;
  const placed = [];
  const byHeight = [...points].sort((a, b) => b.annualised_return - a.annualised_return);
  for (const point of byHeight) {
    const cx = x(point.annualised_volatility);
    const cy = y(point.annualised_return);
    const dot = svgElement("circle", { cx, cy, r: 6, style: `fill: ${assetColour(point.ticker)}` });
    const title = svgElement("title");
    title.textContent = `${labelFor(point.ticker)}: return ${formatPercent(point.annualised_return)}, `
      + `volatility ${formatPercentPlain(point.annualised_volatility, 1)}`;
    dot.append(title);

    let labelY = cy + 4;
    for (const other of placed) {
      if (Math.abs(other.x - cx) < 70 && Math.abs(other.y - labelY) < LABEL_HEIGHT) {
        labelY = other.y + LABEL_HEIGHT;
      }
    }
    placed.push({ x: cx, y: labelY });
    const label = svgElement("text", { x: cx + 10, y: labelY, class: "point-label" });
    label.textContent = labelFor(point.ticker);
    svg.append(dot, label);
  }
  container.append(svg);
}

// Drawdown bars ------------------------------------------------------------

function drawDrawdowns(container, rows) {
  container.replaceChildren();
  const sorted = rows
    .filter((row) => row.maximum_drawdown !== null)
    .sort((a, b) => a.maximum_drawdown - b.maximum_drawdown);
  const worst = Math.min(...sorted.map((row) => row.maximum_drawdown), -0.01);

  for (const row of sorted) {
    const line = document.createElement("div");
    line.className = "bar-row";
    line.title = `Peak ${formatDate(row.peak_date)}, trough ${formatDate(row.trough_date)}`;
    line.innerHTML = `<span class="ticker-cell"></span>`
      + `<div class="bar-track"><div class="bar-fill"></div></div>`
      + `<span class="bar-value"></span>`;
    line.querySelector(".ticker-cell").textContent = labelFor(row.ticker);
    const fill = line.querySelector(".bar-fill");
    fill.style.width = `${(row.maximum_drawdown / worst) * 100}%`;
    fill.style.background = assetColour(row.ticker);
    line.querySelector(".bar-value").textContent = formatPercent(row.maximum_drawdown);
    container.append(line);
  }
}

// Risk table ---------------------------------------------------------------

function drawRiskTable(table, rows) {
  const body = table.querySelector("tbody");
  body.replaceChildren();
  for (const row of rows) {
    const tr = document.createElement("tr");
    const cells = [
      formatPercent(row.total_return),
      formatPercent(row.annualised_return),
      formatPercentPlain(row.annualised_volatility, 1),
      formatPercent(row.maximum_drawdown),
      formatDate(row.peak_date),
      formatDate(row.trough_date),
    ];
    const name = document.createElement("td");
    name.innerHTML = `<span class="ticker-cell"><span class="swatch"></span><span></span></span>`;
    name.querySelector(".swatch").style.background = assetColour(row.ticker);
    name.querySelector(".ticker-cell span:last-child").textContent = labelFor(row.ticker);
    tr.append(name);
    for (const text of cells) {
      const td = document.createElement("td");
      td.textContent = text;
      tr.append(td);
    }
    body.append(tr);
  }
}

// Correlation matrix -------------------------------------------------------

function drawCorrelationMatrix(table, pairs) {
  table.replaceChildren();
  const tickers = visibleAssets().map((asset) => asset.ticker);
  if (tickers.length < 2) {
    const caption = document.createElement("caption");
    caption.className = "note";
    caption.textContent = "Select at least two assets.";
    table.append(caption);
    return;
  }

  const lookup = new Map();
  for (const pair of pairs) {
    lookup.set(`${pair.ticker_x}|${pair.ticker_y}`, pair);
    lookup.set(`${pair.ticker_y}|${pair.ticker_x}`, pair);
  }

  const head = document.createElement("thead");
  const headRow = document.createElement("tr");
  headRow.append(document.createElement("th"));
  for (const ticker of tickers) {
    const th = document.createElement("th");
    th.scope = "col";
    th.textContent = labelFor(ticker);
    headRow.append(th);
  }
  head.append(headRow);

  const body = document.createElement("tbody");
  for (const rowTicker of tickers) {
    const tr = document.createElement("tr");
    const th = document.createElement("th");
    th.scope = "row";
    th.textContent = labelFor(rowTicker);
    tr.append(th);
    for (const columnTicker of tickers) {
      const td = document.createElement("td");
      if (rowTicker === columnTicker) {
        td.textContent = "1.00";
        td.style.color = "var(--text-tertiary)";
      } else {
        const pair = lookup.get(`${rowTicker}|${columnTicker}`);
        const value = pair ? pair.correlation : null;
        if (value === null) {
          td.textContent = "–";
        } else {
          const strength = Math.round(Math.min(Math.abs(value), 1) * 80);
          const tone = value >= 0 ? "var(--positive)" : "var(--negative)";
          td.textContent = value.toFixed(2);
          td.style.background = `color-mix(in srgb, ${tone} ${strength}%, var(--surface-raised))`;
          if (strength > 48) td.style.color = "var(--background)";
          td.title = `${labelFor(rowTicker)} / ${labelFor(columnTicker)}: ${value.toFixed(3)}`
            + ` over ${pair.observations} paired returns`;
        }
      }
      tr.append(td);
    }
    body.append(tr);
  }
  table.append(head, body);
}

// Plain-language summaries -------------------------------------------------

function periodPhrase() {
  const period = state.meta.periods.find((item) => item.key === state.periodKey);
  // "1 year" reads better as "the last year".
  return period.key === "max" ? "Since 2018" : `Over the last ${period.label.replace(/^1 /, "")}`;
}

function setInsight(id, text) {
  document.getElementById(id).textContent = text;
}

function extremes(rows, key) {
  const valid = rows.filter((row) => row[key] !== null && row[key] !== undefined);
  if (valid.length === 0) return null;
  const sorted = [...valid].sort((a, b) => b[key] - a[key]);
  return { highest: sorted[0], lowest: sorted[sorted.length - 1], count: sorted.length };
}

function benchmarkTicker() {
  const index = state.meta.assets.find((asset) => asset.asset_type === "index");
  return index && !state.hidden.has(index.ticker) ? index.ticker : null;
}

function describePerformance(rows) {
  const range = extremes(rows, "total_return");
  if (!range || range.count < 2) return "";
  const parts = [
    `${periodPhrase()}, ${labelFor(range.highest.ticker)} did best `
      + `(${formatPercent(range.highest.total_return)}) and ${labelFor(range.lowest.ticker)} `
      + `did worst (${formatPercent(range.lowest.total_return)}).`,
  ];
  const benchmark = benchmarkTicker();
  const benchmarkRow = rows.find((row) => row.ticker === benchmark);
  if (benchmarkRow) {
    const others = rows.filter((row) => row.ticker !== benchmark && row.total_return !== null);
    const ahead = others.filter((row) => row.total_return > benchmarkRow.total_return).length;
    parts.push(`The ${labelFor(benchmark)} returned ${formatPercent(benchmarkRow.total_return)}; `
      + `${ahead} of the other ${others.length} assets beat it.`);
  }
  return parts.join(" ");
}

function describeVolatility(seriesByTicker) {
  const latest = [];
  for (const asset of visibleAssets()) {
    const points = seriesByTicker[asset.ticker];
    if (points && points.length) {
      const [date, value] = points[points.length - 1];
      latest.push({ ticker: asset.ticker, date, value });
    }
  }
  const range = extremes(latest, "value");
  if (!range) return "";
  const parts = [
    `On ${formatDate(range.highest.date)}, ${labelFor(range.highest.ticker)} was the most volatile `
      + `(${formatPercentPlain(range.highest.value, 1)} a year)`,
  ];
  if (range.count > 1) {
    parts[0] += ` and ${labelFor(range.lowest.ticker)} the calmest `
      + `(${formatPercentPlain(range.lowest.value, 1)}).`;
  } else {
    parts[0] += ".";
  }
  const benchmark = benchmarkTicker();
  const benchmarkPoints = benchmark ? seriesByTicker[benchmark] : null;
  if (benchmarkPoints && benchmarkPoints.length) {
    const peak = benchmarkPoints.reduce((best, point) => (point[1] > best[1] ? point : best));
    parts.push(`In this period the ${labelFor(benchmark)}'s volatility was highest on ${formatDate(peak[0])}, `
      + `at ${formatPercentPlain(peak[1], 1)}.`);
  }
  return parts.join(" ");
}

function describeDrawdowns(rows) {
  const range = extremes(rows, "maximum_drawdown");
  if (!range) return "";
  const worst = range.lowest;
  const parts = [
    `${periodPhrase()}, the deepest fall was ${labelFor(worst.ticker)}'s `
      + `${formatPercent(worst.maximum_drawdown)}, from ${formatDate(worst.peak_date)} `
      + `to ${formatDate(worst.trough_date)}.`,
  ];
  if (range.count > 1) {
    parts.push(`The mildest was ${labelFor(range.highest.ticker)}'s `
      + `${formatPercent(range.highest.maximum_drawdown)}.`);
  }
  return parts.join(" ");
}

function describeRiskReturn(rows) {
  const returns = extremes(rows, "annualised_return");
  const volatility = extremes(rows, "annualised_volatility");
  if (!returns || returns.count < 2) return "";
  const best = returns.highest;
  const calmest = volatility.lowest;
  let text = `Highest yearly return: ${labelFor(best.ticker)} `
    + `(${formatPercent(best.annualised_return)}, with ${formatPercentPlain(best.annualised_volatility, 1)} `
    + `volatility). Lowest volatility: ${labelFor(calmest.ticker)} `
    + `(${formatPercentPlain(calmest.annualised_volatility, 1)}).`;
  if (best.ticker === calmest.ticker) {
    text += " In this period the same asset had both, which is unusual.";
  }
  return text;
}

function correlationStrength(value) {
  const size = Math.abs(value);
  if (size < 0.2) return "were almost unrelated";
  const degree = size < 0.5 ? "weakly" : size < 0.75 ? "clearly" : "very closely";
  return value > 0 ? `moved ${degree} together` : `moved ${degree} in opposite directions`;
}

function describeCorrelations(pairs) {
  const visible = new Set(visibleAssets().map((asset) => asset.ticker));
  const shown = pairs.filter((pair) => visible.has(pair.ticker_x) && visible.has(pair.ticker_y));
  const range = extremes(shown, "correlation");
  if (!range) return "";
  const names = (pair) => `${labelFor(pair.ticker_x)} and ${labelFor(pair.ticker_y)}`;
  const value = (pair) => pair.correlation.toFixed(2);
  const strongest = range.highest;
  if (range.count === 1) {
    return `${periodPhrase()}, ${names(strongest)} ${correlationStrength(strongest.correlation)} `
      + `(${value(strongest)}).`;
  }
  const weakest = range.lowest;
  return `${periodPhrase()}, the strongest link was between ${names(strongest)}, which `
    + `${correlationStrength(strongest.correlation)} (${value(strongest)}). At the other end, `
    + `${names(weakest)} ${correlationStrength(weakest.correlation)} (${value(weakest)}).`;
}

// Controls -----------------------------------------------------------------

function statusMessage(text) {
  const element = document.createElement("p");
  element.className = "note";
  element.textContent = text;
  return element;
}

function buildPeriodControl() {
  const control = document.getElementById("period-control");
  for (const period of state.meta.periods) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = period.label;
    button.dataset.period = period.key;
    button.setAttribute("aria-pressed", String(period.key === state.periodKey));
    button.addEventListener("click", () => selectPeriod(period.key));
    control.append(button);
  }
}

function buildAssetControl() {
  const control = document.getElementById("asset-control");
  for (const asset of state.meta.assets) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "asset-toggle";
    button.setAttribute("aria-pressed", "true");
    button.title = asset.name;
    button.innerHTML = `<span class="swatch"></span><span></span>`;
    button.querySelector(".swatch").style.background = assetColour(asset.ticker);
    button.lastChild.textContent = assetLabel(asset);
    button.addEventListener("click", () => {
      if (state.hidden.has(asset.ticker)) state.hidden.delete(asset.ticker);
      else state.hidden.add(asset.ticker);
      button.setAttribute("aria-pressed", String(!state.hidden.has(asset.ticker)));
      render();
    });
    control.append(button);
  }
}

function buildWindowControl() {
  for (const button of document.querySelectorAll("#window-control button")) {
    button.addEventListener("click", () => {
      state.windowKey = button.dataset.window;
      for (const other of document.querySelectorAll("#window-control button")) {
        other.setAttribute("aria-pressed", String(other === button));
      }
      render();
    });
  }
}

async function selectPeriod(key) {
  state.periodKey = key;
  for (const button of document.querySelectorAll("#period-control button")) {
    button.setAttribute("aria-pressed", String(button.dataset.period === key));
  }
  if (!state.periods[key]) {
    state.periods[key] = await loadJson(`${DATA_DIR}/${key}.json`);
  }
  render();
}

// Rendering ----------------------------------------------------------------

function render() {
  const period = state.periods[state.periodKey];
  if (!period) return;
  const visible = new Set(visibleAssets().map((asset) => asset.ticker));
  const riskRows = period.risk_profile.filter((row) => visible.has(row.ticker));

  drawLineChart(document.getElementById("cumulative-chart"), period.cumulative_return, {
    label: "Cumulative return by asset",
    includeZero: true,
    format: (value) => formatPercent(value),
  });
  drawLineChart(document.getElementById("volatility-chart"), period[state.windowKey], {
    label: "Annualised rolling volatility by asset",
    includeZero: true,
    format: (value) => formatPercentPlain(value, 1),
  });
  drawDrawdowns(document.getElementById("drawdown-bars"), riskRows);
  drawScatter(document.getElementById("risk-scatter"), riskRows);
  drawRiskTable(document.getElementById("risk-table"), riskRows);
  drawCorrelationMatrix(document.getElementById("correlation-matrix"), period.correlations);

  setInsight("performance-insight", describePerformance(riskRows));
  setInsight("volatility-insight", describeVolatility(period[state.windowKey]));
  setInsight("drawdown-insight", describeDrawdowns(riskRows));
  setInsight("scatter-insight", describeRiskReturn(riskRows));
  setInsight("correlation-insight", describeCorrelations(period.correlations));
}

async function loadJson(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
  return response.json();
}

async function start() {
  const snapshot = document.getElementById("snapshot");
  try {
    state.meta = await loadJson(`${DATA_DIR}/meta.json`);
  } catch (error) {
    snapshot.textContent = "The data snapshot could not be loaded. "
      + "If you opened this file directly, serve the folder instead: python -m http.server -d site";
    console.error(error);
    return;
  }
  snapshot.textContent = `Data snapshot up to ${formatDate(state.meta.snapshot_date)}. `
    + "End-of-day historical data, not real-time.";

  buildPeriodControl();
  buildAssetControl();
  buildWindowControl();
  await selectPeriod(state.periodKey);

  let resizeTimer = null;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(render, 150);
  });
}

start();
