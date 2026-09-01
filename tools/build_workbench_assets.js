const fs = require("fs");
const path = require("path");

const repoRoot = path.resolve(__dirname, "..");
const sourceRoot = path.join(
  repoRoot,
  "backend",
  "overseas_costing",
  "overseas_costing",
  "page",
  "overseas_cost_workbench"
);
const runtimeRoot = path.join(
  repoRoot,
  "backend",
  "overseas_costing",
  "overseas_costing",
  "overseas_costing",
  "page",
  "overseas_cost_workbench"
);
const partsRoot = path.join(sourceRoot, "parts");

const jsParts = [
  "00-bootstrap.js",
  "10-shell.js",
  "20-data-filters.js",
  "30-calculation-erp.js",
  "40-vouchers.js",
  "50-import-category.js",
  "60-purchase-source.js",
  "65-manual-documents.js",
  "70-attachments.js",
  "75-table-and-list.js",
  "76-allocation.js",
  "80-drawer-profit.js",
  "90-audit-logs.js",
  "95-focus-and-selection.js",
  "100-crud-edit.js",
  "110-helpers.js",
];

const cssParts = [
  "00-foundation.css",
  "10-shell.css",
  "20-desk-layout.css",
  "30-dialogs-and-forms.css",
  "40-wide-layout.css",
  "50-responsive-and-drawer.css",
  "60-mobile-layout.css",
];

function readParts(names) {
  return names.map((name) => {
    const file = path.join(partsRoot, name);
    if (!fs.existsSync(file)) {
      throw new Error(`Missing workbench source part: ${path.relative(repoRoot, file)}`);
    }
    return fs.readFileSync(file, "utf8").trimEnd();
  }).join("\n\n") + "\n";
}

function writeOutputs(filename, content) {
  for (const root of [sourceRoot, runtimeRoot]) {
    fs.mkdirSync(root, { recursive: true });
    fs.writeFileSync(path.join(root, filename), content, "utf8");
  }
}

writeOutputs("overseas_cost_workbench.js", readParts(jsParts));
writeOutputs("overseas_cost_workbench.css", readParts(cssParts));

console.log(`Built workbench assets from ${jsParts.length} JS parts and ${cssParts.length} CSS parts.`);
console.log(`Outputs: ${path.relative(repoRoot, sourceRoot)} and ${path.relative(repoRoot, runtimeRoot)}`);
