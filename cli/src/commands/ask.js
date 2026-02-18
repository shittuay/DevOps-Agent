import ora from 'ora';
import { streamChat } from '../lib/api-client.js';
import { renderMarkdown, error, printModelInfo, printCredits } from '../lib/output.js';

async function ask(question) {
  if (!question && !process.stdin.isTTY) {
    // Read from pipe
    const chunks = [];
    for await (const chunk of process.stdin) {
      chunks.push(chunk);
    }
    question = Buffer.concat(chunks).toString().trim();
  }

  if (!question) {
    error('No question provided. Usage: devopsagent ask "your question"');
    process.exit(1);
  }

  const spinner = ora('Thinking...').start();
  let firstChunk = true;
  let fullContent = '';

  try {
    for await (const event of streamChat(question)) {
      if (event.type === 'chunk') {
        if (firstChunk) {
          spinner.stop();
          firstChunk = false;
        }
        process.stdout.write(event.content);
        fullContent += event.content;
      } else if (event.type === 'done') {
        if (firstChunk) spinner.stop();
        // End with newline if content didn't end with one
        if (fullContent && !fullContent.endsWith('\n')) {
          process.stdout.write('\n');
        }
        printModelInfo(event.model_info);
        printCredits(event.credits_remaining);
      } else if (event.type === 'error') {
        if (firstChunk) spinner.fail('Error');
        error(event.content);
        process.exit(1);
      }
    }
  } catch (err) {
    spinner.fail('Request failed');
    error(err.message);
    process.exit(1);
  }
}

export function registerAskCommand(program) {
  program
    .command('ask [question...]')
    .description('Ask a single question and get a response')
    .action(async (parts) => {
      const question = parts?.length ? parts.join(' ') : null;
      await ask(question);
    });
}
