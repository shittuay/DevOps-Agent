import chalk from 'chalk';
import { Marked } from 'marked';
import { markedTerminal } from 'marked-terminal';

const marked = new Marked(markedTerminal());

export function renderMarkdown(text) {
  if (!text) return '';
  return marked.parse(text);
}

export function info(msg) {
  process.stderr.write(chalk.blue(msg) + '\n');
}

export function success(msg) {
  process.stderr.write(chalk.green(msg) + '\n');
}

export function warn(msg) {
  process.stderr.write(chalk.yellow(msg) + '\n');
}

export function error(msg) {
  process.stderr.write(chalk.red(msg) + '\n');
}

export function dim(msg) {
  process.stderr.write(chalk.dim(msg) + '\n');
}

export function printModelInfo(modelInfo) {
  if (!modelInfo) return;
  dim(`Model: ${modelInfo.display_name || modelInfo.model} (${modelInfo.provider})`);
}

export function printCredits(credits) {
  if (credits === undefined || credits === null) return;
  dim(`Credits remaining: ${credits}`);
}

export function printTable(rows, columns, format = 'table') {
  if (!rows || rows.length === 0) {
    dim('(no results)');
    return;
  }

  if (format === 'json') {
    console.log(JSON.stringify(rows, null, 2));
    return;
  }

  // Calculate column widths
  const widths = columns.map(col => col.length);
  for (const row of rows) {
    columns.forEach((col, i) => {
      const val = String(row[col] ?? '');
      if (val.length > widths[i]) widths[i] = val.length;
    });
  }

  const header = columns.map((col, i) => col.padEnd(widths[i])).join('  ');
  const divider = widths.map(w => '-'.repeat(w)).join('  ');

  console.log(chalk.bold(header));
  console.log(chalk.dim(divider));
  for (const row of rows) {
    const line = columns.map((col, i) => String(row[col] ?? '').padEnd(widths[i])).join('  ');
    console.log(line);
  }
}
