import { Command } from 'commander';
import { registerAuthCommands } from './commands/auth.js';
import { registerChatCommand } from './commands/chat.js';
import { registerAskCommand } from './commands/ask.js';
import { registerConfigCommands } from './commands/config.js';
import { registerAwsCommands } from './commands/aws.js';
import { registerK8sCommands } from './commands/k8s.js';
import { registerTerraformCommands } from './commands/terraform.js';
import { registerDockerCommands } from './commands/docker.js';

const program = new Command();

program
  .name('devopsagent')
  .description('DevOps Agent CLI - AI-powered infrastructure management')
  .version('1.0.0');

registerAuthCommands(program);
registerChatCommand(program);
registerAskCommand(program);
registerConfigCommands(program);
registerAwsCommands(program);
registerK8sCommands(program);
registerTerraformCommands(program);
registerDockerCommands(program);

program.parse();
