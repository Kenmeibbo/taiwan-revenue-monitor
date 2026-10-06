/* PDF pages are drawn separately to bound memory and preserve browser CJK fonts. */
(() => {
  "use strict";
  const WIDTH = 1684;
  const HEIGHT = 1190;
  const MARGIN = 48;
  const FONT = '"Microsoft JhengHei", "PingFang TC", "Noto Sans CJK TC", sans-serif';
  const columns = [
    ["\u5e8f", 64, false], ["\u5e02\u5834", 64, false], ["\u4ee3\u865f", 74, false],
    ["\u516c\u53f8", 170, false], ["\u7522\u696d", 130, false], ["\u6708\u4efd", 98, false],
    ["\u7576\u6708\u71df\u6536", 170, true], ["\u4e0a\u6708\u71df\u6536", 170, true],
    ["\u53bb\u5e74\u540c\u6708", 170, true], ["\u5e74\u589e\u7387", 100, true],
    ["10 \u5e74\u55ae\u6708\u6700\u9ad8", 180, true], ["\u65b0\u9ad8", 70, false],
  ];
  const scale = (WIDTH - MARGIN * 2) / columns.reduce((sum, col) => sum + col[1], 0);
  const widths = columns.map((col) => col[1] * scale);
  const numberFormat = new Intl.NumberFormat("zh-TW");
  const money = (value) => value === null || value === undefined ? "-" : numberFormat.format(value);
  const percent = (value) => value === null || value === undefined || value === "" || !Number.isFinite(Number(value))
    ? "-" : Number(value).toFixed(2) + "%";

  function wrap(ctx, text, width) {
    const lines = [];
    let line = "";
    for (const char of String(text ?? "-")) {
      if (char === "\n") {
        lines.push(line);
        line = "";
      } else if (line && ctx.measureText(line + char).width > width) {
        lines.push(line);
        line = char;
      } else {
        line += char;
      }
    }
    lines.push(line);
    return lines;
  }

  function rowValues(row, index, complete) {
    return [
      String(index + 1), row.marketLabel, row.companyId, row.companyName,
      row.industry || "-", row.dataYmDisplay, money(row.monthlyRevenue),
      money(row.previousMonthRevenue), money(row.lastYearMonthRevenue),
      percent(row.yoyPct), complete ? money(row.historicalSameMonthMax) : "-",
      complete && row.isNewHigh ? "\u65b0\u9ad8" : "-",
    ];
  }

  async function download(report, progress) {
    const { payload, rows } = report;
    if (!rows.length) throw new Error("\u76ee\u524d\u6c92\u6709\u53ef\u4e0b\u8f09\u7684\u8cc7\u6599\u3002");
    progress("\u6b63\u5728\u7522\u751f PDF\u2026");
    await document.fonts.ready;
    const canvas = document.createElement("canvas");
    canvas.width = WIDTH * 1.5;
    canvas.height = HEIGHT * 1.5;
    const ctx = canvas.getContext("2d", { alpha: false });
    if (!ctx) throw new Error("\u6b64\u700f\u89bd\u5668\u7121\u6cd5\u7522\u751f PDF\u3002");
    ctx.scale(1.5, 1.5);
    ctx.font = "18px " + FONT;
    ctx.textBaseline = "middle";
    const filters = [
      "\u529f\u80fd\uff1a" + report.filters[0], "\u5e02\u5834\uff1a" + report.filters[1],
      "\u7522\u696d\uff1a" + report.filters[2], "\u641c\u5c0b\uff1a" + (report.keyword || "\u5168\u90e8"),
    ].join("  |  ");
    const metadata = [
      ...wrap(ctx, filters, WIDTH - 2 * MARGIN),
      "\u7be9\u9078\u7d50\u679c\uff1a" + rows.length + " \u6a94  |  \u71df\u6536\u55ae\u4f4d\uff1a\u65b0\u81fa\u5e63\u4edf\u5143",
      "\u8cc7\u6599\u67e5\u8a62\u6642\u9593\uff1a" + (payload.generatedAt || "-") + "  |  \u532f\u51fa\u6642\u9593\uff1a" + report.exportedAt + "\uff08\u81fa\u5317\uff09",
      ...wrap(ctx, [
        "\u4f86\u6e90\uff1a\u516c\u958b\u8cc7\u8a0a\u89c0\u6e2c\u7ad9\uff1b\u4ee5\u4e0a\u70ba\u532f\u51fa\u7576\u4e0b\u8cc7\u6599\u3002",
        payload.partial || payload.syncing ? "\u672c\u6708\u8cc7\u6599\u5c1a\u672a\u9f4a\u5168\uff0c\u50c5\u5217\u5df2\u53d6\u5f97\u516c\u53f8\u3002" : "",
        !payload.historyComplete ? "\u6b77\u53f2\u8cc7\u6599\u672a\u9f4a\u5168\uff0c\u672a\u5224\u5b9a\u65b0\u9ad8\u3002" : "",
      ].filter(Boolean).join(" "), WIDTH - 2 * MARGIN),
    ];
    const tableTop = 110 + metadata.length * 25;
    const bodyTop = tableTop + 42;
    const bodyBottom = HEIGHT - 70;
    if (bodyTop + 50 > bodyBottom) throw new Error("\u7be9\u9078\u689d\u4ef6\u6587\u5b57\u904e\u9577\uff0c\u8acb\u7e2e\u77ed\u641c\u5c0b\u5167\u5bb9\u3002");
    const pages = [];
    let page = [], y = bodyTop;
    for (let index = 0; index < rows.length; index++) {
      const cells = rowValues(rows[index], index, payload.historyComplete)
        .map((value, col) => wrap(ctx, value, widths[col] - 16));
      const height = Math.max(34, Math.max(...cells.map((lines) => lines.length)) * 22 + 14);
      if (height > bodyBottom - bodyTop) throw new Error("\u516c\u53f8\u6b04\u4f4d\u6587\u5b57\u904e\u9577\uff0c\u7121\u6cd5\u653e\u5165 PDF \u9801\u9762\u3002");
      if (y + height > bodyBottom) {
        pages.push(page);
        page = [];
        y = bodyTop;
      }
      page.push({ cells, height, index });
      y += height;
    }
    if (page.length) pages.push(page);
    const doc = new window.jspdf.jsPDF({ orientation: "landscape", unit: "mm", format: "a4", compress: true });
    doc.setProperties({ title: "Taiwan monthly revenue " + payload.selectedMonthDisplay, creator: "Taiwan Revenue Monitor" });
    try {
      for (let pageIndex = 0; pageIndex < pages.length; pageIndex++) {
        ctx.fillStyle = "#ffffff";
        ctx.fillRect(0, 0, WIDTH, HEIGHT);
        ctx.textAlign = "left";
        ctx.fillStyle = "#172026";
        ctx.font = "bold 32px " + FONT;
        ctx.fillText("\u53f0\u80a1\u6708\u71df\u6536\u67e5\u8a62  " + payload.selectedMonthDisplay, MARGIN, 64);
        ctx.font = "18px " + FONT;
        ctx.fillStyle = "#42545c";
        metadata.forEach((line, index) => ctx.fillText(line, MARGIN, 110 + index * 25));
        ctx.fillStyle = "#e6f3f1";
        ctx.fillRect(MARGIN, tableTop, WIDTH - MARGIN * 2, 42);
        let x = MARGIN;
        ctx.fillStyle = "#172026";
        columns.forEach((col, index) => {
          ctx.textAlign = col[2] ? "right" : "left";
          ctx.fillText(col[0], col[2] ? x + widths[index] - 8 : x + 8, tableTop + 21);
          x += widths[index];
        });
        let rowY = bodyTop;
        for (const row of pages[pageIndex]) {
          ctx.fillStyle = row.index % 2 ? "#f3f6f7" : "#ffffff";
          ctx.fillRect(MARGIN, rowY, WIDTH - MARGIN * 2, row.height);
          x = MARGIN;
          ctx.fillStyle = "#172026";
          row.cells.forEach((lines, col) => {
            ctx.textAlign = columns[col][2] ? "right" : "left";
            const textX = columns[col][2] ? x + widths[col] - 8 : x + 8;
            lines.forEach((line, i) => ctx.fillText(line, textX, rowY + 18 + i * 22));
            x += widths[col];
          });
          rowY += row.height;
          ctx.strokeStyle = "#d8e0e5";
          ctx.beginPath();
          ctx.moveTo(MARGIN, rowY);
          ctx.lineTo(WIDTH - MARGIN, rowY);
          ctx.stroke();
        }
        ctx.textAlign = "left";
        ctx.fillStyle = "#42545c";
        ctx.fillText("TWSE / TPEx Revenue Monitor", MARGIN, HEIGHT - 35);
        ctx.textAlign = "right";
        ctx.fillText("\u7b2c " + (pageIndex + 1) + " / " + pages.length + " \u9801", WIDTH - MARGIN, HEIGHT - 35);
        if (pageIndex) doc.addPage();
        doc.addImage(canvas.toDataURL("image/png"), "PNG", 0, 0, 297, 210, undefined, "FAST");
        progress("\u6b63\u5728\u7522\u751f PDF\uff1a" + (pageIndex + 1) + " / " + pages.length + " \u9801");
        await new Promise((resolve) => setTimeout(resolve, 0));
      }
      await doc.save("taiwan-revenue-" + payload.selectedMonth + "-" + payload.mode + "-" + rows.length + ".pdf", { returnPromise: true });
    } finally {
      canvas.width = canvas.height = 0;
    }
  }
  window.RevenuePdf = { download };
})();


