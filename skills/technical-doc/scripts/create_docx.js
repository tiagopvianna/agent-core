#!/usr/bin/env node

const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawnSync } = require("child_process");

let docx;

try {
  docx = require("docx");
} catch (err) {
  console.error(
    "Missing dependency: docx\n" +
    "Install it with: npm install docx"
  );
  process.exit(1);
}

const {
  Document,
  Packer,
  Paragraph,
  TextRun,
  ImageRun,
  HeadingLevel,
  AlignmentType,
  LevelFormat,
  Footer,
  PageNumber,
  Table,
  TableRow,
  TableCell,
  WidthType,
  BorderStyle,
  ShadingType,
} = docx;

const { renderDiagram } = require("./diagram");

let rasterizerState;

const [inputPath, outputPath] = process.argv.slice(2);

if (!inputPath || !outputPath) {
  console.error(
    "Usage: node create_docx.js <input.md> <output.docx>"
  );
  process.exit(1);
}

if (!fs.existsSync(inputPath)) {
  console.error(`Input file not found: ${inputPath}`);
  process.exit(1);
}

function inlineRuns(text, boldAll = false) {
  const runs = [];
  if (boldAll) {
    return [new TextRun({ text, bold: true })];
  }
  const regex = /(\*\*.*?\*\*|`.*?`|\*[^*]+\*)/g;

  let lastIndex = 0;
  let match;

  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      runs.push(
        new TextRun(text.slice(lastIndex, match.index))
      );
    }

    const token = match[0];

    if (token.startsWith("**")) {
      runs.push(
        new TextRun({
          text: token.slice(2, -2),
          bold: true,
        })
      );
    } else if (token.startsWith("`")) {
      runs.push(
        new TextRun({
          text: token.slice(1, -1),
          font: "Courier New",
          size: 20,
        })
      );
    } else if (token.startsWith("*")) {
      runs.push(
        new TextRun({
          text: token.slice(1, -1),
          italics: true,
        })
      );
    }

    lastIndex = regex.lastIndex;
  }

  if (lastIndex < text.length) {
    runs.push(
      new TextRun(text.slice(lastIndex))
    );
  }

  return runs;
}

function normalParagraph(text) {
  return new Paragraph({
    children: inlineRuns(text),
    spacing: {
      after: 180,
      line: 300,
    },
  });
}

function heading(text, level) {
  const levels = {
    1: HeadingLevel.TITLE,
    2: HeadingLevel.HEADING_1,
    3: HeadingLevel.HEADING_2,
  };

  return new Paragraph({
    text,
    heading: levels[level] || HeadingLevel.HEADING_2,
    spacing: {
      before: level === 1 ? 0 : 280,
      after: 140,
    },
  });
}

function rasterizeSvg(svgPath) {
  const pngPath = `${svgPath}.png`;
  const rasterizer = path.join(__dirname, "rasterize_svg.swift");
  if (!rasterizerState) {
    const buildDir = fs.mkdtempSync(path.join(os.tmpdir(), "technical-doc-rasterizer-"));
    const cacheDir = path.join(buildDir, "module-cache");
    const binaryPath = path.join(buildDir, "rasterize_svg");
    fs.mkdirSync(cacheDir, { recursive: true });
    const compile = spawnSync("swiftc", [rasterizer, "-o", binaryPath], {
      encoding: "utf8",
      env: {
        ...process.env,
        SWIFT_MODULECACHE_PATH: cacheDir,
        CLANG_MODULE_CACHE_PATH: cacheDir,
      },
    });
    if (compile.error || compile.status !== 0 || !fs.existsSync(binaryPath)) {
      const detail = (compile.stderr || compile.error?.message || "unknown error").trim();
      throw new Error(`Unable to build SVG rasterizer. Install macOS Swift/AppKit support or use PNG input. ${detail}`);
    }
    rasterizerState = { binaryPath, cacheDir };
  }

  const result = spawnSync(rasterizerState.binaryPath, [svgPath, pngPath], {
    encoding: "utf8",
    env: {
      ...process.env,
      SWIFT_MODULECACHE_PATH: rasterizerState.cacheDir,
      CLANG_MODULE_CACHE_PATH: rasterizerState.cacheDir,
    },
  });

  if (result.error || result.status !== 0 || !fs.existsSync(pngPath)) {
    const detail = (result.stderr || result.error?.message || "unknown error").trim();
    throw new Error(`Unable to rasterize SVG fallback. Install Swift/AppKit support or use PNG input. ${detail}`);
  }

  return fs.readFileSync(pngPath);
}

function readImageDimensions(imagePath, data) {
  const extension = path.extname(imagePath).toLowerCase();
  if (extension === ".png" && data.length >= 24) {
    return { width: data.readUInt32BE(16), height: data.readUInt32BE(20) };
  }

  if (extension === ".svg") {
    const source = data.toString("utf8");
    const viewBox = source.match(/viewBox\s*=\s*["']\s*[-\d.]+\s+[-\d.]+\s+([\d.]+)\s+([\d.]+)\s*["']/i);
    const width = source.match(/\bwidth\s*=\s*["']\s*([\d.]+)/i);
    const height = source.match(/\bheight\s*=\s*["']\s*([\d.]+)/i);
    if (viewBox) return { width: Number(viewBox[1]), height: Number(viewBox[2]) };
    if (width && height) return { width: Number(width[1]), height: Number(height[1]) };
  }

  if ((extension === ".jpg" || extension === ".jpeg") && data.length > 4) {
    for (let offset = 2; offset < data.length - 9;) {
      if (data[offset] !== 0xff) { offset += 1; continue; }
      const marker = data[offset + 1];
      const length = data.readUInt16BE(offset + 2);
      if (marker >= 0xc0 && marker <= 0xc3) {
        return { width: data.readUInt16BE(offset + 7), height: data.readUInt16BE(offset + 5) };
      }
      offset += 2 + length;
    }
  }

  return { width: 570, height: 360 };
}

function imageParagraph(imagePath, altText = "", dimensions = null) {
  const extension = path.extname(imagePath).toLowerCase();
  const data = fs.readFileSync(imagePath);
  const isSvg = extension === ".svg";
  const fallback = isSvg ? rasterizeSvg(imagePath) : null;
  const sourceDimensions = dimensions || readImageDimensions(imagePath, data);
  const maxWidth = 570;
  const width = maxWidth;
  const height = Math.max(1, Math.round(maxWidth * sourceDimensions.height / sourceDimensions.width));
  const image = isSvg
    ? new ImageRun({
        type: "svg",
        data,
        fallback: { type: "png", data: fallback },
        transformation: { width, height },
      })
    : new ImageRun({
        type: extension === ".jpg" || extension === ".jpeg" ? "jpg" : "png",
        data,
        transformation: { width, height },
      });

  return new Paragraph({
    alignment: AlignmentType.CENTER,
    children: [image],
    spacing: { before: 120, after: 180 },
  });
}

function isTableSeparator(line) {
  return /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?\s*$/.test(line);
}

function splitTableRow(line) {
  const normalized = line.trim().replace(/^\|/, "").replace(/\|$/, "");
  return normalized.split("|").map((cell) => cell.trim());
}

function tableFromRows(rows) {
  const columnCount = Math.max(...rows.map((row) => row.length));
  const columnWidths = Array.from({ length: columnCount }, () => Math.floor(9000 / columnCount));
  const borders = {
    top: { style: BorderStyle.SINGLE, size: 4, color: "B7C5D3" },
    bottom: { style: BorderStyle.SINGLE, size: 4, color: "B7C5D3" },
    left: { style: BorderStyle.SINGLE, size: 4, color: "B7C5D3" },
    right: { style: BorderStyle.SINGLE, size: 4, color: "B7C5D3" },
    insideH: { style: BorderStyle.SINGLE, size: 4, color: "D7E0E8" },
    insideV: { style: BorderStyle.SINGLE, size: 4, color: "D7E0E8" },
  };
  return new Table({
    width: { size: 9000, type: WidthType.DXA },
    columnWidths,
    borders,
    rows: rows.map((row, rowIndex) => new TableRow({
      children: Array.from({ length: columnCount }, (_, columnIndex) => new TableCell({
        width: { size: columnWidths[columnIndex], type: WidthType.DXA },
        shading: rowIndex === 0 ? { type: ShadingType.CLEAR, fill: "E7EEF6" } : undefined,
        children: [new Paragraph({
          children: inlineRuns(row[columnIndex] || "", rowIndex === 0),
          spacing: { after: 40, line: 240 },
        })],
      })),
    })),
  });
}

function parseMarkdown(markdown, baseDir) {
  const lines = markdown.replace(/\r\n/g, "\n").split("\n");
  const children = [];

  let paragraphBuffer = [];
  let diagramBuffer = null;

  function flushParagraph() {
    if (!paragraphBuffer.length) return;

    const text = paragraphBuffer.join(" ").trim();

    if (text) {
      children.push(normalParagraph(text));
    }

    paragraphBuffer = [];
  }

  for (let lineIndex = 0; lineIndex < lines.length; lineIndex += 1) {
    const rawLine = lines[lineIndex];
    const line = rawLine.trim();

    if (diagramBuffer) {
      if (line === "```") {
        try {
          const spec = JSON.parse(diagramBuffer.join("\n"));
          const svgPath = path.join(require("os").tmpdir(), `technical-doc-diagram-${Date.now()}-${children.length}.svg`);
          fs.writeFileSync(svgPath, renderDiagram(spec), "utf8");
          flushParagraph();
          const dimensions = spec.width && spec.height ? { width: spec.width, height: spec.height } : null;
          children.push(imageParagraph(svgPath, spec.title, dimensions));
        } catch (err) {
          throw new Error(`Invalid diagram block: ${err.message}`);
        }
        diagramBuffer = null;
      } else {
        diagramBuffer.push(rawLine);
      }
      continue;
    }

    if (line === "```diagram") {
      flushParagraph();
      diagramBuffer = [];
      continue;
    }

    if (!line) {
      flushParagraph();
      continue;
    }

    if (line.includes("|") && lineIndex + 1 < lines.length && isTableSeparator(lines[lineIndex + 1].trim())) {
      flushParagraph();
      const rows = [splitTableRow(line)];
      lineIndex += 2;
      while (lineIndex < lines.length && lines[lineIndex].trim() && lines[lineIndex].includes("|")) {
        rows.push(splitTableRow(lines[lineIndex]));
        lineIndex += 1;
      }
      lineIndex -= 1;
      children.push(tableFromRows(rows));
      continue;
    }

    const imageMatch = line.match(/^!\[([^\]]*)\]\(([^)]+)\)$/);
    if (imageMatch) {
      flushParagraph();
      const imagePath = path.resolve(baseDir, imageMatch[2]);
      if (!fs.existsSync(imagePath)) {
        throw new Error(`Image file not found: ${imagePath}`);
      }
      children.push(imageParagraph(imagePath, imageMatch[1]));
      continue;
    }

    if (line.startsWith("### ")) {
      flushParagraph();
      children.push(heading(line.slice(4), 3));
      continue;
    }

    if (line.startsWith("## ")) {
      flushParagraph();
      children.push(heading(line.slice(3), 2));
      continue;
    }

    if (line.startsWith("# ")) {
      flushParagraph();
      children.push(heading(line.slice(2), 1));
      continue;
    }

    if (/^[-*]\s+/.test(line)) {
      flushParagraph();

      children.push(
        new Paragraph({
          children: inlineRuns(
            line.replace(/^[-*]\s+/, "")
          ),
          numbering: {
            reference: "bullet-list",
            level: 0,
          },
          spacing: {
            after: 100,
          },
        })
      );

      continue;
    }

    if (/^\d+\.\s+/.test(line)) {
      flushParagraph();

      children.push(
        new Paragraph({
          children: inlineRuns(
            line.replace(/^\d+\.\s+/, "")
          ),
          numbering: {
            reference: "number-list",
            level: 0,
          },
          spacing: {
            after: 100,
          },
        })
      );

      continue;
    }

    paragraphBuffer.push(line);
  }

  flushParagraph();

  if (diagramBuffer) {
    throw new Error("Unclosed diagram block; expected a closing ``` line.");
  }

  return children;
}

async function main() {
  const markdown = fs.readFileSync(inputPath, "utf8");
  const children = parseMarkdown(markdown, path.dirname(path.resolve(inputPath)));

  if (!children.length) {
    console.error("Input document contains no content.");
    process.exit(1);
  }

  const document = new Document({
    styles: {
      default: {
        document: {
          run: {
            font: "Calibri",
            size: 22,
            color: "172638",
          },
          paragraph: {
            spacing: {
              line: 300,
            },
          },
        },
      },

      paragraphStyles: [
        {
          id: "Title",
          name: "Title",
          basedOn: "Normal",
          next: "Normal",
          quickFormat: true,
          run: {
            size: 38,
            bold: true,
            color: "365F91",
          },
          paragraph: {
            spacing: {
              after: 300,
            },
          },
        },
        {
          id: "Heading1",
          name: "Heading 1",
          basedOn: "Normal",
          next: "Normal",
          quickFormat: true,
          run: {
            size: 28,
            bold: true,
            color: "365F91",
          },
          paragraph: {
            spacing: {
              before: 300,
              after: 140,
            },
          },
        },
        {
          id: "Heading2",
          name: "Heading 2",
          basedOn: "Normal",
          next: "Normal",
          quickFormat: true,
          run: {
            size: 24,
            bold: true,
            color: "4F81BD",
          },
          paragraph: {
            spacing: {
              before: 220,
              after: 120,
            },
          },
        },
      ],
    },

    numbering: {
      config: [
        {
          reference: "bullet-list",
          levels: [
            {
              level: 0,
              format: LevelFormat.BULLET,
              text: "•",
              alignment: AlignmentType.LEFT,
              style: {
                paragraph: {
                  indent: {
                    left: 720,
                    hanging: 360,
                  },
                },
              },
            },
          ],
        },

        {
          reference: "number-list",
          levels: [
            {
              level: 0,
              format: LevelFormat.DECIMAL,
              text: "%1.",
              alignment: AlignmentType.LEFT,
              style: {
                paragraph: {
                  indent: {
                    left: 720,
                    hanging: 360,
                  },
                },
              },
            },
          ],
        },
      ],
    },

    sections: [
      {
        properties: {
          page: {
            margin: {
            top: 1080,
            right: 1260,
            bottom: 1080,
            left: 1260,
            },
          },
        },

        children,

        footers: {
          default: new Footer({
            children: [
              new Paragraph({
                alignment: AlignmentType.RIGHT,
                children: [
                  new TextRun({
                    text: "Page ",
                    color: "777777",
                    size: 18,
                  }),
                  new TextRun({
                    children: [PageNumber.CURRENT],
                    color: "777777",
                    size: 18,
                  }),
                ],
              }),
            ],
          }),
        },
      },
    ],
  });

  const outputDir = path.dirname(
    path.resolve(outputPath)
  );

  fs.mkdirSync(outputDir, {
    recursive: true,
  });

  const buffer = await Packer.toBuffer(document);

  fs.writeFileSync(outputPath, buffer);

  console.log(path.resolve(outputPath));
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
