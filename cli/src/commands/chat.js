import { createInterface } from 'node:readline';
import chalk from 'chalk';
import { streamChat, createConversation } from '../lib/api-client.js';
import { error, dim, printModelInfo, printCredits } from '../lib/output.js';

async function chat() {
  console.log(chalk.bold('DevOps Agent - Interactive Chat'));
  dim('Type your message and press Enter. Type "exit" or Ctrl+C to quit.');
  dim('Type "/new" to start a new conversation.\n');

  let conversationId = null;

  const rl = createInterface({
    input: process.stdin,
    output: process.stdout,
    prompt: chalk.cyan('you> '),
  });

  rl.prompt();

  rl.on('line', async (line) => {
    const input = line.trim();

    if (!input) {
      rl.prompt();
      return;
    }

    if (input === 'exit' || input === 'quit') {
      dim('\nGoodbye!');
      rl.close();
      process.exit(0);
    }

    if (input === '/new') {
      conversationId = null;
      dim('Started new conversation.\n');
      rl.prompt();
      return;
    }

    // Pause readline while streaming
    rl.pause();

    process.stdout.write(chalk.green('agent> '));

    let fullContent = '';
    try {
      for await (const event of streamChat(input, conversationId)) {
        if (event.type === 'chunk') {
          process.stdout.write(event.content);
          fullContent += event.content;
        } else if (event.type === 'done') {
          if (fullContent && !fullContent.endsWith('\n')) {
            process.stdout.write('\n');
          }
          conversationId = event.conversation_id || conversationId;
          printModelInfo(event.model_info);
          printCredits(event.credits_remaining);
        } else if (event.type === 'error') {
          if (!fullContent) {
            // Clear the "agent> " prefix on error with no content
            process.stdout.write('\n');
          }
          error(`Error: ${event.content}`);
        }
      }
    } catch (err) {
      process.stdout.write('\n');
      error(err.message);
    }

    console.log('');
    rl.resume();
    rl.prompt();
  });

  rl.on('close', () => {
    process.exit(0);
  });
}

export function registerChatCommand(program) {
  program
    .command('chat')
    .description('Start an interactive chat session')
    .action(chat);
}
