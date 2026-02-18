import { createInterface } from 'node:readline';
import ora from 'ora';
import { validateKey, getMe } from '../lib/api-client.js';
import {
  getApiKey, setApiKey, removeApiKey, getServerUrl, getConfigPath,
} from '../lib/config-manager.js';
import { success, error, info, dim } from '../lib/output.js';

function prompt(question) {
  const rl = createInterface({ input: process.stdin, output: process.stderr });
  return new Promise((resolve) => {
    rl.question(question, (answer) => {
      rl.close();
      resolve(answer.trim());
    });
  });
}

async function login() {
  const existing = getApiKey();
  if (existing) {
    info('You are already logged in. Run `devopsagent logout` first to switch accounts.');
    return;
  }

  const serverUrl = getServerUrl();
  info(`Server: ${serverUrl}`);
  info('Get your API key from your account settings at /api-gateway/keys\n');

  const key = await prompt('API Key: ');
  if (!key) {
    error('No API key provided.');
    process.exit(1);
  }

  const spinner = ora('Validating API key...').start();
  try {
    const result = await validateKey(key, serverUrl);
    spinner.succeed('API key validated');

    setApiKey(key);

    const user = result.user;
    success(`Logged in as ${user.username || user.email}`);
    dim(`Config saved to ${getConfigPath()}`);
  } catch (err) {
    spinner.fail('Validation failed');
    error(err.message || 'Invalid API key');
    process.exit(1);
  }
}

async function logout() {
  const key = getApiKey();
  if (!key) {
    info('Not logged in.');
    return;
  }
  removeApiKey();
  success('Logged out. API key removed.');
}

async function whoami() {
  const key = getApiKey();
  if (!key) {
    error('Not logged in. Run `devopsagent login` first.');
    process.exit(1);
  }

  const spinner = ora('Fetching account info...').start();
  try {
    const data = await getMe();
    spinner.stop();

    const user = data.user;
    console.log(`Username:  ${user.username || 'N/A'}`);
    console.log(`Email:     ${user.email}`);
    console.log(`User ID:   ${user.id}`);

    if (data.subscription) {
      console.log(`Tier:      ${data.subscription.tier || 'free'}`);
      console.log(`Credits:   ${data.subscription.credits_remaining}`);
    }
  } catch (err) {
    spinner.fail('Failed to fetch account info');
    error(err.message);
    process.exit(1);
  }
}

export function registerAuthCommands(program) {
  program
    .command('login')
    .description('Authenticate with your DevOps Agent API key')
    .action(login);

  program
    .command('logout')
    .description('Remove stored API key')
    .action(logout);

  program
    .command('whoami')
    .description('Show current user info and credits')
    .action(whoami);
}
