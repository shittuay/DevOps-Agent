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
