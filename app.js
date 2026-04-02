import React, { useState } from "https://esm.sh/react@18.3.1";
import { createRoot } from "https://esm.sh/react-dom@18.3.1/client";
import { LEDGER_SUMMARY_MARKDOWN } from "./data.js";

const h = React.createElement;

const FIXED_CATEGORY_COLORS = {
  보험: "#b4572f",
  구독: "#d77b38",
  대출: "#e0ab4c",
  통신비: "#6d82d8",
  자동차: "#4f97b7",
  교육: "#5c9672",
  주거: "#d16b73",
  연금: "#7e74c9",
  청년도약계좌: "#85725c",
  용돈: "#bf8c34",
};

function parseWon(value) {
  return Number(String(value || "").replace(/[^\d]/g, "")) || 0;
}

function formatWon(value) {
  return `${new Intl.NumberFormat("ko-KR").format(Math.abs(Math.round(value)))}원`;
}

function parseSections(markdown) {
  const lines = markdown.split(/\r?\n/);
  const sections = new Map();
  let currentHeading = null;

  for (const line of lines) {
    if (line.startsWith("## ")) {
      currentHeading = line.replace("## ", "").trim();
      sections.set(currentHeading, []);
      continue;
    }
    if (currentHeading) {
      sections.get(currentHeading).push(line);
    }
  }

  return sections;
}

function extractMetric(lines, keyword) {
  const targetLine = lines.find((line) => line.includes(keyword));
  return parseWon(targetLine);
}

function extractFixedExpenseCategories(lines) {
  return lines
    .filter((line) => /^- [^:]+: [\d,]+원$/.test(line.trim()))
    .filter((line) => !line.includes("매월 고정지출 총액(추정):"))
    .map((line) => {
      const [label, rawValue] = line.trim().replace(/^- /, "").split(": ");
      return { label, value: parseWon(rawValue) };
    });
}

function simplifyFixedSectionLine(line) {
  const match = line.match(/^(\s*-\s+)([^:]+:\s*[\d,]+원)(?:\s*\/.*)?$/);
  if (!match) {
    return line;
  }
  return `${match[1]}${match[2]}`;
}

function parseFixedDetailCards(lines) {
  const cards = [];
  let currentCard = null;

  lines.map((line) => simplifyFixedSectionLine(line)).forEach((line) => {
    const rootMatch = line.match(/^- ([^:]+): ([\d,]+원)$/);
    const childMatch = line.match(/^  - ([^:]+): ([\d,]+원)$/);

    if (rootMatch && !line.includes("매월 고정지출 총액(추정):")) {
      currentCard = {
        title: rootMatch[1],
        amount: rootMatch[2],
        items: [],
      };
      cards.push(currentCard);
      return;
    }

    if (childMatch && currentCard) {
      currentCard.items.push({
        label: childMatch[1],
        amount: childMatch[2],
      });
    }
  });

  return cards;
}

function toWonNumber(valueText) {
  return parseWon(valueText);
}

function toWonText(value) {
  return formatWon(value);
}

function buildCategoriesFromCards(cards) {
  return cards.map((card) => ({
    label: card.title,
    value: card.items.length
      ? card.items.reduce((sum, item) => sum + toWonNumber(item.amount), 0)
      : toWonNumber(card.amount),
  }));
}

function buildAsIsCards(cards) {
  return cards
    .map((card) => {
      if (card.title === "용돈") {
        const filteredItems = card.items.filter((item) => item.label === "이축복");
        const total = filteredItems.reduce((sum, item) => sum + toWonNumber(item.amount), 0);
        return { ...card, amount: toWonText(total), items: filteredItems };
      }

      if (card.title === "자동차") {
        const filteredItems = card.items.filter((item) => item.label !== "주차 평균");
        const total = filteredItems.reduce((sum, item) => sum + toWonNumber(item.amount), 0);
        return { ...card, amount: toWonText(total), items: filteredItems };
      }

      return card;
    })
    .filter((card) => card.items.length || toWonNumber(card.amount) > 0);
}

function buildToBeCards(cards) {
  return cards
    .map((card) => {
      if (card.title === "용돈") {
        const nextItems = [
          { label: "이축복 용돈", amount: toWonText(300000) },
          { label: "최수연 용돈", amount: toWonText(200000) },
          { label: "이하나 용돈", amount: toWonText(20000) },
          { label: "장모님", amount: toWonText(150000) },
        ];
        const total = nextItems.reduce((sum, item) => sum + toWonNumber(item.amount), 0);
        return { ...card, amount: toWonText(total), items: nextItems };
      }

      return card;
    })
    .filter((card) => card.items.length || toWonNumber(card.amount) > 0);
}

function buildDiffCategories(asIsCategories, toBeCategories) {
  const labels = Array.from(
    new Set([...asIsCategories.map((item) => item.label), ...toBeCategories.map((item) => item.label)]),
  );

  return labels.map((label) => {
    const asIs = asIsCategories.find((item) => item.label === label)?.value || 0;
    const toBe = toBeCategories.find((item) => item.label === label)?.value || 0;
    return { label, asIs, toBe, diff: toBe - asIs };
  });
}

function buildDiffDetails(asIsCards, toBeCards, label) {
  const asIsCard = asIsCards.find((card) => card.title === label);
  const toBeCard = toBeCards.find((card) => card.title === label);
  return {
    asIsItems: asIsCard ? asIsCard.items : [],
    toBeItems: toBeCard ? toBeCard.items : [],
  };
}

function buildDonutGradient(items) {
  if (!items.length) {
    return "conic-gradient(#dddad1 0deg 360deg)";
  }

  const total = items.reduce((sum, item) => sum + item.value, 0);
  if (!total) {
    return "conic-gradient(#dddad1 0deg 360deg)";
  }

  let current = 0;
  return `conic-gradient(${items
    .map((item, index) => {
      const start = current;
      const angle = (item.value / total) * 360;
      current += angle;
      return `${FIXED_CATEGORY_COLORS[item.label] || Object.values(FIXED_CATEGORY_COLORS)[index % Object.values(FIXED_CATEGORY_COLORS).length]} ${start}deg ${current}deg`;
    })
    .join(", ")})`;
}

function InsightCard({ label, value, meta, tone = "default" }) {
  return h(
    "article",
    { className: `insight-card tone-${tone}` },
    h("span", { className: "insight-label" }, label),
    h("strong", { className: "insight-value" }, value),
    h("span", { className: "insight-meta" }, meta),
  );
}

function FixedExpensePanel({ fixedCategories, cards, title, subtitle }) {
  const [isOpen, setIsOpen] = useState(false);
  const total = fixedCategories.reduce((sum, item) => sum + item.value, 0);
  const maxValue = Math.max(...fixedCategories.map((item) => item.value), 1);

  return h(
    "section",
    { className: "panel" },
    h(
      "div",
      { className: "panel-head panel-head-spread" },
      h(
        "div",
        null,
        h("h2", null, title),
        h("p", { className: "panel-copy" }, subtitle),
      ),
    ),
    h(
      "div",
      { className: "bar-chart" },
      fixedCategories.map((item) =>
        h(
          "div",
          { className: "bar-row", key: item.label },
          h(
            "div",
            {
              className: `bar-label ${item.label === "청년도약계좌" ? "bar-label-compact" : ""}`,
            },
            item.label,
          ),
          h(
            "div",
            { className: "bar-track" },
            h("div", {
              className: "bar-fill",
              style: {
                width: `${(item.value / maxValue) * 100}%`,
                background: FIXED_CATEGORY_COLORS[item.label] || "#b4572f",
              },
            }),
          ),
          h("div", { className: "bar-value" }, formatWon(item.value)),
        ),
      ),
    ),
    h(
      "div",
      { className: "donut-panel" },
      h(
        "div",
        { className: "donut-wrap" },
        h(
          "div",
          { className: "donut-chart", style: { background: buildDonutGradient(fixedCategories) } },
          h(
            "div",
            { className: "donut-center" },
            h("span", { className: "donut-center-label" }, "월 고정지출"),
            h("strong", { className: "donut-center-value" }, formatWon(total)),
          ),
        ),
      ),
      h(
        "div",
        { className: "donut-legend" },
        fixedCategories.map((item) =>
          h(
            "div",
            { className: "legend-row", key: item.label },
            h("span", {
              className: "legend-dot",
              style: { background: FIXED_CATEGORY_COLORS[item.label] || "#b4572f" },
            }),
            h(
              "span",
              {
                className: `legend-label ${item.label === "청년도약계좌" ? "legend-label-compact" : ""}`,
              },
              item.label,
            ),
            h("span", { className: "legend-value" }, formatWon(item.value)),
          ),
        ),
      ),
    ),
    h(
      "div",
      { className: "detail-section" },
      h(
        "div",
        { className: "detail-section-head detail-section-head-spread" },
        h(
          "div",
          null,
          h("h3", null, "고정지출 상세"),
          h("p", null, ".md 파일 기준으로 고정값을 반영한 상세 카드"),
        ),
        h(
          "button",
          {
            className: "toggle-button",
            type: "button",
            onClick: () => setIsOpen((current) => !current),
            "aria-expanded": isOpen,
          },
          isOpen ? "닫기" : "열기",
        ),
      ),
      isOpen
        ? h(
            "div",
            { className: "fixed-card-grid" },
            cards.map((card) =>
              h(
                "article",
                {
                  className: "fixed-detail-card",
                  key: card.title,
                  style: { "--card-accent": FIXED_CATEGORY_COLORS[card.title] || "#b4572f" },
                },
                h(
                  "div",
                  { className: "fixed-detail-head" },
                  h(
                    "span",
                    {
                      className: `fixed-detail-title ${card.title === "청년도약계좌" ? "fixed-detail-title-compact" : ""}`,
                    },
                    card.title,
                  ),
                  h("strong", { className: "fixed-detail-amount" }, card.amount),
                ),
                h(
                  "div",
                  { className: "fixed-detail-items" },
                  card.items.map((item) =>
                    h(
                      "div",
                      { className: "fixed-detail-item", key: `${card.title}-${item.label}` },
                      h("span", { className: "fixed-detail-item-label" }, item.label),
                      h("span", { className: "fixed-detail-item-amount" }, item.amount),
                    ),
                  ),
                ),
              ),
            ),
          )
        : h("div", { className: "detail-collapsed" }, "열기를 누르면 고정지출 상세 항목이 나타납니다."),
    ),
  );
}

function TabButton({ id, activeTab, label, onSelect }) {
  return h(
    "button",
    {
      className: `tab-button ${activeTab === id ? "is-active" : ""}`,
      type: "button",
      onClick: () => onSelect(id),
    },
    label,
  );
}

function DiffPanel({
  diffCategories,
  asIsCards,
  toBeCards,
  asIsFixedTotal,
  toBeFixedTotal,
  asIsDisposableValue,
  toBeDisposableValue,
}) {
  const changedCategories = diffCategories.filter((item) => item.diff !== 0);
  const maxDiff = Math.max(...changedCategories.map((item) => Math.abs(item.diff)), 1);
  const fixedDiff = toBeFixedTotal - asIsFixedTotal;
  const disposableDiff = toBeDisposableValue - asIsDisposableValue;

  return h(
    "section",
    { className: "panel" },
    h(
      "div",
      { className: "panel-head" },
      h("h2", null, "AS-IS / TO-BE 차이점"),
      h("p", { className: "panel-copy" }, "실제로 변경된 고정지출 카테고리만 골라서 증감과 전체 변화폭을 비교"),
    ),
    h(
      "div",
      { className: "hero-grid" },
      h(InsightCard, {
        label: "고정지출 차이",
        value: `${fixedDiff > 0 ? "+" : ""}${formatWon(fixedDiff)}`,
        meta: "TO-BE - AS-IS",
        tone: fixedDiff > 0 ? "warning" : "highlight",
      }),
      h(InsightCard, {
        label: "생활비가용금액 차이",
        value: `${disposableDiff > 0 ? "+" : ""}${formatWon(disposableDiff)}`,
        meta: "TO-BE - AS-IS",
        tone: disposableDiff >= 0 ? "highlight" : "warning",
      }),
      h(InsightCard, {
        label: "비교 기준",
        value: `${changedCategories.length}개`,
        meta: "변경된 카테고리 수",
      }),
    ),
    h(
      "div",
      { className: "diff-chart" },
      changedCategories.map((item) =>
        h(
          "div",
          { className: "diff-row", key: item.label },
          h("div", { className: "diff-label" }, item.label),
          h(
            "div",
            { className: "diff-track" },
            h("div", { className: "diff-axis" }),
            h("div", {
              className: `diff-fill ${item.diff >= 0 ? "is-up" : "is-down"}`,
              style: { width: `${(Math.abs(item.diff) / maxDiff) * 50}%` },
            }),
          ),
          h(
            "div",
            { className: `diff-value ${item.diff >= 0 ? "is-up" : "is-down"}` },
            `${item.diff > 0 ? "+" : ""}${formatWon(item.diff)}`,
          ),
        ),
      ),
    ),
    h(
      "div",
      { className: "detail-section" },
      h(
        "div",
        { className: "detail-section-head" },
        h("h3", null, "변경 항목 요약"),
        h("p", null, "AS-IS 대비 TO-BE에서 조정된 항목과 상세 구성의 변화"),
      ),
      h(
        "div",
        { className: "fixed-card-grid" },
        changedCategories.map((item) => {
          const detail = buildDiffDetails(asIsCards, toBeCards, item.label);

          return h(
            "article",
            {
              className: "fixed-detail-card",
              key: `diff-${item.label}`,
              style: { "--card-accent": FIXED_CATEGORY_COLORS[item.label] || "#b4572f" },
            },
            h(
              "div",
              { className: "fixed-detail-head" },
              h("span", { className: "fixed-detail-title" }, item.label),
              h(
                "strong",
                { className: "fixed-detail-amount" },
                `${item.diff > 0 ? "+" : ""}${formatWon(item.diff)}`,
              ),
            ),
            h(
              "div",
              { className: "fixed-detail-items" },
              h(
                "div",
                { className: "fixed-detail-item" },
                h("span", { className: "fixed-detail-item-label" }, "AS-IS"),
                h("span", { className: "fixed-detail-item-amount" }, formatWon(item.asIs)),
              ),
              h(
                "div",
                { className: "fixed-detail-item" },
                h("span", { className: "fixed-detail-item-label" }, "TO-BE"),
                h("span", { className: "fixed-detail-item-amount" }, formatWon(item.toBe)),
              ),
            ),
            h(
              "div",
              { className: "diff-detail-grid" },
              h(
                "div",
                { className: "diff-detail-column" },
                h("h4", null, "AS-IS 상세"),
                ...(detail.asIsItems.length
                  ? detail.asIsItems.map((entry) =>
                      h(
                        "div",
                        { className: "fixed-detail-item", key: `asis-${item.label}-${entry.label}` },
                        h("span", { className: "fixed-detail-item-label" }, entry.label),
                        h("span", { className: "fixed-detail-item-amount" }, entry.amount),
                      ),
                    )
                  : [
                      h(
                        "div",
                        { className: "fixed-detail-item", key: `asis-empty-${item.label}` },
                        h("span", { className: "fixed-detail-item-label" }, "변경 없음"),
                        h("span", { className: "fixed-detail-item-amount" }, "-"),
                      ),
                    ]),
              ),
              h(
                "div",
                { className: "diff-detail-column" },
                h("h4", null, "TO-BE 상세"),
                ...(detail.toBeItems.length
                  ? detail.toBeItems.map((entry) =>
                      h(
                        "div",
                        { className: "fixed-detail-item", key: `tobe-${item.label}-${entry.label}` },
                        h("span", { className: "fixed-detail-item-label" }, entry.label),
                        h("span", { className: "fixed-detail-item-amount" }, entry.amount),
                      ),
                    )
                  : [
                      h(
                        "div",
                        { className: "fixed-detail-item", key: `tobe-empty-${item.label}` },
                        h("span", { className: "fixed-detail-item-label" }, "변경 없음"),
                        h("span", { className: "fixed-detail-item-amount" }, "-"),
                      ),
                    ]),
              ),
            ),
          );
        }),
      ),
    ),
  );
}

function HeroSummary({ title, subtitle, salaryBase, fixedTotal, disposableValue }) {
  return h(
    React.Fragment,
    null,
    h(
      "div",
      { className: "hero-summary-head" },
      h("h2", null, title),
      h("p", null, subtitle),
    ),
    h(
      "div",
      { className: "hero-grid" },
      h(InsightCard, {
        label: "내 급여",
        value: formatWon(salaryBase),
        meta: "월 급여 기준",
      }),
      h(InsightCard, {
        label: "월 고정지출",
        value: formatWon(fixedTotal),
        meta: "고정지출 총액",
        tone: "warning",
      }),
      h(InsightCard, {
        label: "생활비가용금액",
        value: formatWon(disposableValue),
        meta: "월급 - 고정지출",
        tone: "highlight",
      }),
    ),
  );
}

function App() {
  const [activeTab, setActiveTab] = useState("as_is");

  const sectionMap = parseSections(LEDGER_SUMMARY_MARKDOWN);
  const fixedLines = sectionMap.get("고정지출") || [];
  const disposableLines = sectionMap.get("생활비가용금액") || [];

  const fixedCards = parseFixedDetailCards(fixedLines);
  const salaryBase = extractMetric(disposableLines, "월 급여 기준:");
  const asIsCards = buildAsIsCards(fixedCards);
  const toBeCards = buildToBeCards(fixedCards);
  const asIsCategories = buildCategoriesFromCards(asIsCards);
  const toBeCategories = buildCategoriesFromCards(toBeCards);
  const asIsFixedTotal = asIsCategories.reduce((sum, item) => sum + item.value, 0);
  const toBeFixedTotal = toBeCategories.reduce((sum, item) => sum + item.value, 0);
  const asIsDisposableValue = salaryBase - asIsFixedTotal;
  const toBeDisposableValue = salaryBase - toBeFixedTotal;
  const diffCategories = buildDiffCategories(asIsCategories, toBeCategories);

  return h(
    "main",
    { className: "page-shell" },
    h(
      "section",
      { className: "hero" },
      h("p", { className: "eyebrow" }, "AUTO LEDGER"),
      h("h1", null, "고정지출 대시보드"),
      h(
        "p",
        { className: "hero-copy" },
        "GitHub Pages 게시용으로 고정 데이터를 묶었습니다. AS-IS, TO-BE, 차이점을 같은 화면에서 안정적으로 비교할 수 있습니다.",
      ),
      h(
        "div",
        { className: "tab-bar" },
        h(TabButton, { id: "as_is", activeTab, label: "AS-IS", onSelect: setActiveTab }),
        h(TabButton, { id: "to_be", activeTab, label: "TO-BE", onSelect: setActiveTab }),
        h(TabButton, { id: "diff", activeTab, label: "차이점", onSelect: setActiveTab }),
      ),
      activeTab === "as_is"
        ? h(HeroSummary, {
            title: "AS-IS 요약",
            subtitle: "현재 기준으로 조정된 AS-IS 고정지출 구조",
            salaryBase,
            fixedTotal: asIsFixedTotal,
            disposableValue: asIsDisposableValue,
          })
        : activeTab === "to_be"
          ? h(HeroSummary, {
              title: "TO-BE 요약",
              subtitle: "목표 구조를 반영한 TO-BE 고정지출 구조",
              salaryBase,
              fixedTotal: toBeFixedTotal,
              disposableValue: toBeDisposableValue,
            })
          : h(HeroSummary, {
              title: "차이점 요약",
              subtitle: "AS-IS와 TO-BE 사이에서 실제로 달라지는 지점만 비교",
              salaryBase,
              fixedTotal: toBeFixedTotal - asIsFixedTotal,
              disposableValue: toBeDisposableValue - asIsDisposableValue,
            }),
    ),
    activeTab === "as_is"
      ? h(FixedExpensePanel, {
          fixedCategories: asIsCategories,
          cards: asIsCards,
          title: "AS-IS 고정지출 구조",
          subtitle: "현재 실제 데이터 기준 카테고리별 월 지출 규모와 비중",
        })
      : null,
    activeTab === "to_be"
      ? h(FixedExpensePanel, {
          fixedCategories: toBeCategories,
          cards: toBeCards,
          title: "TO-BE 고정지출 구조",
          subtitle: "조정된 목표 구조를 기준으로 본 카테고리별 월 지출 규모와 비중",
        })
      : null,
    activeTab === "diff"
      ? h(DiffPanel, {
          diffCategories,
          asIsCards,
          toBeCards,
          asIsFixedTotal,
          toBeFixedTotal,
          asIsDisposableValue,
          toBeDisposableValue,
        })
      : null,
  );
}

createRoot(document.getElementById("root")).render(h(App));
