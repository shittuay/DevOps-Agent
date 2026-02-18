import { Command } from 'commander';
import { registerAuthCommands } from './commands/auth.js';
import { registerChatCommand } from './commands/chat.js';
import { registerAskCommand } from './commands/ask.js';
import { registerConfigCommands } from './commands/config.js';

const program = new Command();

program
  .name('devopsagent')
  .description('DevOps Agent CLI - AI-powered infrastructure management')
  .version('1.0.0');

registerAuthCommands(program);
registerChatCommand(program);
registerAskCommand(program);
registerConfigCommands(program);

program.parse();
