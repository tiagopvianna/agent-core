#!/usr/bin/env node

const fs = require("fs");

const COLORS = {
  ink: "#172638",
  line: "#405467",
  blue: { fill: "#e7eef6", stroke: "#5c7ea0" },
  green: { fill: "#dff1e1", stroke: "#2f8248" },
  amber: { fill: "#fff0d3", stroke: "#bd8100" },
  red: { fill: "#f8dfe0", stroke: "#bd3e3e" },
  gray: { fill: "#f3f5f7", stroke: "#8795a3" },
};

function escapeXml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

function wrapText(text, maxChars) {
  const words = String(text ?? "").split(/\s+/);
  const lines = [];
  let line = "";
  for (const word of words) {
    const next = line ? `${line} ${word}` : word;
    if (line && next.length > maxChars) {
      lines.push(line);
      line = word;
    } else {
      line = next;
    }
  }
  if (line) lines.push(line);
  return lines.length ? lines : [""];
}

function colorFor(variant) {
  return COLORS[variant] || COLORS.blue;
}

function renderText(text, x, y, options = {}) {
  const lines = wrapText(text, options.maxChars || 58);
  const lineHeight = options.lineHeight || 25;
  const anchor = options.anchor || "start";
  const weight = options.weight || 400;
  return lines.map((line, index) =>
    `<text x="${x}" y="${y + index * lineHeight}" text-anchor="${anchor}" ` +
    `font-family="Arial" font-size="${options.size || 22}" ` +
    `font-weight="${weight}" fill="${options.color || COLORS.ink}">${escapeXml(line)}</text>`
  ).join("");
}

function arrowHead(x, y, fromX, fromY) {
  const angle = Math.atan2(y - fromY, x - fromX);
  const length = 16;
  const halfWidth = 8;
  const backX = x - Math.cos(angle) * length;
  const backY = y - Math.sin(angle) * length;
  const leftX = backX + Math.cos(angle + Math.PI / 2) * halfWidth;
  const leftY = backY + Math.sin(angle + Math.PI / 2) * halfWidth;
  const rightX = backX + Math.cos(angle - Math.PI / 2) * halfWidth;
  const rightY = backY + Math.sin(angle - Math.PI / 2) * halfWidth;
  return `<polygon points="${x},${y} ${leftX},${leftY} ${rightX},${rightY}" fill="${COLORS.line}"/>`;
}

function buildFlowSpec(spec) {
  const width = Number(spec.width || 1200);
  const margin = Number(spec.margin || 45);
  const titleHeight = spec.title ? 58 : 0;
  const pipelineY = margin + titleHeight;
  const pipelineGap = Number(spec.pipelineGap || 80);
  const defaultNodeHeight = Number(spec.nodeHeight || 90);
  const pipeline = spec.pipeline || [];
  const nodes = [];
  let cursorX = margin;

  for (const item of pipeline) {
    const node = {
      ...item,
      id: item.id || `pipeline-${nodes.length + 1}`,
      label: item.label || item.id || "",
      x: item.x ?? cursorX,
      y: item.y ?? pipelineY,
      w: item.w || 250,
      h: item.h || defaultNodeHeight,
      variant: item.variant || "blue",
    };
    nodes.push(node);
    cursorX = node.x + node.w + pipelineGap;
  }

  const branchX = Number(spec.branchX || 145);
  const branchWidth = Number(spec.branchWidth || width - branchX - margin);
  const branchGap = Number(spec.branchGap || 38);
  const branchTop = Number(spec.branchTop || pipelineY + defaultNodeHeight + 120);
  const branches = spec.branches || [];
  let branchY = branchTop;
  const branchNodes = [];

  for (const item of branches) {
    const maxChars = item.maxChars || Math.max(36, Math.floor(branchWidth / 16));
    const lineCount = wrapText(item.label || "", maxChars).length;
    const branch = {
      ...item,
      id: item.id || `branch-${branchNodes.length + 1}`,
      label: item.label || "",
      x: item.x ?? branchX,
      y: item.y ?? branchY,
      w: item.w || branchWidth,
      h: item.h || Math.max(82, 42 + lineCount * 25),
      maxChars,
      variant: item.variant || "gray",
    };
    branchNodes.push(branch);
    branchY = branch.y + branch.h + branchGap;
  }

  const paths = [];
  const last = nodes[nodes.length - 1];
  if (last && branchNodes.length) {
    const spineX = Number(spec.spineX || branchX - 42);
    const spineY = branchNodes[0].y - 48;
    const startX = last.x + last.w / 2;
    const startY = last.y + last.h;
    const bottomY = branchNodes[branchNodes.length - 1].y + branchNodes[branchNodes.length - 1].h / 2;
    paths.push({ d: `M ${startX} ${startY} L ${startX} ${spineY} L ${spineX} ${spineY} L ${spineX} ${bottomY}`, arrow: false });
    for (const branch of branchNodes) {
      paths.push({ d: `M ${spineX} ${branch.y + branch.h / 2} L ${branch.x} ${branch.y + branch.h / 2}`, arrow: true, arrowX: branch.x, arrowY: branch.y + branch.h / 2, arrowFromX: spineX, arrowFromY: branch.y + branch.h / 2 });
    }
  }

  const computedHeight = Math.max(760, branchY + margin - branchGap);
  return {
    ...spec,
    width,
    height: Number(spec.height || computedHeight),
    nodes: [...nodes, ...branchNodes],
    edges: nodes.slice(0, -1).map((node, index) => ({ from: node.id, to: nodes[index + 1].id })),
    paths,
  };
}

function renderDiagram(spec) {
  if (spec.layout === "flow") spec = buildFlowSpec(spec);
  const width = Number(spec.width || 1200);
  const height = Number(spec.height || 760);
  const margin = Number(spec.margin || 40);
  const title = spec.title || "";
  const titleHeight = title ? 66 : 20;
  const nodes = new Map((spec.nodes || []).map((node) => [node.id, node]));
  const svg = [];

  svg.push(`<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">`);
  svg.push(`<rect x="0" y="0" width="${width}" height="${height}" fill="#ffffff"/>`);
  svg.push(`<defs><marker id="arrow" markerWidth="10" markerHeight="10" refX="8" refY="5" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="${COLORS.line}"/></marker></defs>`);
  if (title) svg.push(renderText(title, margin, margin + 3, { size: 30, weight: 700, color: "#365f91", maxChars: 80 }));

  for (const routedPath of spec.paths || []) {
    svg.push(`<path d="${routedPath.d}" fill="none" stroke="${COLORS.line}" stroke-width="4"/>`);
    if (routedPath.arrow) svg.push(arrowHead(routedPath.arrowX ?? 0, routedPath.arrowY ?? 0, routedPath.arrowFromX, routedPath.arrowFromY));
  }

  for (const edge of spec.edges || []) {
    const from = nodes.get(edge.from);
    const to = nodes.get(edge.to);
    if (!from || !to) continue;
    const start = { x: from.x + from.w, y: from.y + from.h / 2 };
    const end = { x: to.x, y: to.y + to.h / 2 };
    let path = `M ${start.x} ${start.y} L ${end.x} ${end.y}`;
    if (edge.via) {
      const points = edge.via.map((point) => `${point.x} ${point.y}`).join(" L ");
      path = `M ${start.x} ${start.y} L ${points} L ${end.x} ${end.y}`;
    }
    svg.push(`<path d="${path}" fill="none" stroke="${COLORS.line}" stroke-width="4"/>`);
    const previous = edge.via && edge.via.length ? edge.via[edge.via.length - 1] : start;
    svg.push(arrowHead(end.x, end.y, previous.x, previous.y));
    if (edge.label) svg.push(renderText(edge.label, edge.labelX || (start.x + end.x) / 2, edge.labelY || (start.y + end.y) / 2 - 8, { size: 17, anchor: "middle", maxChars: 48 }));
  }

  for (const node of spec.nodes || []) {
    const palette = colorFor(node.variant);
    const radius = node.radius || 10;
    svg.push(`<rect x="${node.x}" y="${node.y}" width="${node.w}" height="${node.h}" rx="${radius}" fill="${palette.fill}" stroke="${palette.stroke}" stroke-width="3"/>`);
    const lines = wrapText(node.label, node.maxChars || Math.max(18, Math.floor(node.w / 16)));
    const startY = node.y + node.h / 2 - ((lines.length - 1) * 25) / 2 + 8;
    svg.push(renderText(node.label, node.x + (node.padding || 20), startY, { size: node.size || 22, maxChars: node.maxChars || Math.max(18, Math.floor(node.w / 16)), weight: node.weight || 400 }));
  }

  for (const band of spec.bands || []) {
    const palette = colorFor(band.variant || "gray");
    svg.push(`<rect x="${band.x}" y="${band.y}" width="${band.w}" height="${band.h}" rx="${band.radius || 10}" fill="${palette.fill}" stroke="${palette.stroke}" stroke-width="3"/>`);
    svg.push(renderText(band.label, band.x + (band.padding || 20), band.y + (band.textY || 42), { size: band.size || 22, maxChars: band.maxChars || Math.floor(band.w / 16) }));
  }

  svg.push("</svg>");
  return svg.join("");
}

function readSpec(specPath) {
  return JSON.parse(fs.readFileSync(specPath, "utf8"));
}

module.exports = { renderDiagram, readSpec };

