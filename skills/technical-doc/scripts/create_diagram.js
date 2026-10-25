#!/usr/bin/env node

const fs = require("fs");
const path = require("path");
const { renderDiagram, readSpec } = require("./diagram");

const [inputPath, outputPath] = process.argv.slice(2);
if (!inputPath || !outputPath) {
  console.error("Usage: node create_diagram.js <diagram.json> <diagram.svg>");
  process.exit(1);
}
if (!fs.existsSync(inputPath)) {
  console.error(`Input file not found: ${inputPath}`);
  process.exit(1);
}

const output = path.resolve(outputPath);
fs.mkdirSync(path.dirname(output), { recursive: true });
fs.writeFileSync(output, renderDiagram(readSpec(inputPath)), "utf8");
console.log(output);

