import { loadConfig, setConfigValue, getConfigPath } from '../lib/config-manager.js';
import { info, error, dim } from '../lib/output.js';

function configShow() {
  const config = loadConfig();
  dim(`Config file: ${getConfigPath()}\n`);

  for (const [key, value] of Object.entries(config)) {
    if (key === 'api_key' && value) {
      // Mask the API key
      console.log(`  ${key}: ${value.slice(0, 8)}...${'*'.repeat(16)}`);
    } else {
      console.log(`  ${key}: ${value}`);
    }
  }
}

function configSet(key, value) {
  if (!key || value === undefined) {
    error('Usage: devopsagent config set <key> <value>');
    process.exit(1);
  }

  if (key === 'api_key') {
    error('Use `devopsagent login` to set your API key.');
    process.exit(1);
  }

  setConfigValue(key, value);
  info(`Set ${key} = ${value}`);
}

export function registerConfigCommands(program) {
  const configCmd = program
    .command('config')
    .description('Manage CLI configuration');

  configCmd
    .command('show')
    .description('Show current configuration')
    .action(configShow);

  configCmd
    .command('set <key> <value>')
    .description('Set a configuration value')
    .action(configSet);
}
