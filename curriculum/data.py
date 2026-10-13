"""
Static curriculum data — source of truth.
Based on The Complete DevOps Bootcamp (Udemy).
No database needed for content; only progress is persisted.
"""

CURRICULUM = [
    {
        "phase": "01",
        "title": "Linux & Networking",
        "duration": "3-4 weeks",
        "color": "#00FFB2",
        "description": "Build the bedrock. Master the command line before everything else.",
        "modules": [
            {
                "id": "linux-cli",
                "title": "Linux CLI & Shell Basics",
                "topics": [
                    "Navigating the file system: ls, cd, pwd, find",
                    "File operations: cp, mv, rm, mkdir, chmod, chown",
                    "VI editor: insert mode, save, quit, search & replace",
                    "Text processing: grep, awk, sed, cat, head, tail",
                    "Shell scripting: variables, loops, conditionals, functions",
                    "Process management: ps, top, kill, jobs, bg, fg",
                ],
                "project": "Write a server health-check script that monitors CPU, memory, disk and logs alerts to a file",
                "resources": [
                    {"title": "Linux Command Line (KodeKloud)", "url": "https://kodekloud.com/courses/the-linux-basics-course/"},
                ],
            },
            {
                "id": "linux-packages-services",
                "title": "Package Management & Services",
                "topics": [
                    "apt / yum / dnf: install, update, remove packages",
                    "Managing system services with systemd and systemctl",
                    "Enabling, disabling, starting and stopping services",
                    "Viewing service status and reading logs with journalctl",
                    "Scheduling tasks with cron and at",
                ],
                "project": "Install and configure Nginx as a service that auto-starts on boot",
                "resources": [],
            },
            {
                "id": "linux-networking",
                "title": "Networking & DNS",
                "topics": [
                    "Switching and routing: ip, route, arp",
                    "Network diagnostics: ping, traceroute, netstat, ss, curl",
                    "DNS concepts: A records, CNAME, MX, TTL",
                    "DNS resolution: /etc/hosts, /etc/resolv.conf, nslookup, dig",
                    "Firewalls and port management: iptables, ufw",
                    "SSH: key-based auth, config file, tunneling",
                ],
                "project": "Set up a local DNS server and configure two VMs to resolve each other by hostname",
                "resources": [],
            },
        ],
    },
    {
        "phase": "02",
        "title": "Git & Source Control",
        "duration": "1-2 weeks",
        "color": "#00C2FF",
        "description": "Version everything. Collaborate without chaos.",
        "modules": [
            {
                "id": "git-fundamentals",
                "title": "Git Fundamentals",
                "topics": [
                    "Initializing a repository: git init, git status, git log",
                    "Staging and committing: git add, git commit, .gitignore",
                    "Viewing history: git log, git diff, git show",
                    "Undoing changes: git reset, git revert, git stash",
                    "Tagging releases: git tag",
                ],
                "project": "Initialize a repo for a sample app, make structured commits following conventional commit style",
                "resources": [
                    {"title": "Pro Git Book (free)", "url": "https://git-scm.com/book/en/v2"},
                ],
            },
            {
                "id": "git-branching",
                "title": "Branching & Merging",
                "topics": [
                    "Creating and switching branches: git branch, git checkout, git switch",
                    "Merging strategies: fast-forward, recursive, squash",
                    "Rebasing: git rebase, interactive rebase",
                    "Resolving merge conflicts step by step",
                    "Branching strategies: GitFlow, trunk-based development",
                ],
                "project": "Simulate a feature branch workflow: create branch, develop, raise PR, resolve conflict, merge",
                "resources": [],
            },
            {
                "id": "git-remote",
                "title": "Remote Repositories & Collaboration",
                "topics": [
                    "Connecting to GitHub/GitLab: git remote, git push, git pull",
                    "Cloning repositories: git clone",
                    "Fetching vs pulling: git fetch, git pull",
                    "Pull requests and code reviews workflow",
                    "Forking a project and contributing upstream",
                    "Git hooks for pre-commit and pre-push automation",
                ],
                "project": "Fork an open-source DevOps tool, make an improvement, and open a pull request",
                "resources": [],
            },
        ],
    },
    {
        "phase": "03",
        "title": "CI/CD with Jenkins",
        "duration": "2-3 weeks",
        "color": "#FF6B35",
        "description": "Automate the path from code to production.",
        "modules": [
            {
                "id": "cicd-concepts",
                "title": "CI/CD Concepts & Build Tools",
                "topics": [
                    "What is CI/CD and why it matters",
                    "Build tools overview: Maven/Gradle (Java), npm (Node), pip (Python)",
                    "Compiling, testing and packaging applications",
                    "Build artifacts: JARs, WARs, tarballs, npm packages",
                    "Understanding application dependencies and dependency managers",
                ],
                "project": "Package a sample Java app into a JAR and a Node app into an npm package from the CLI",
                "resources": [],
            },
            {
                "id": "jenkins-setup",
                "title": "Jenkins Setup & Administration",
                "topics": [
                    "Installing Jenkins on a VM and via Docker",
                    "Navigating the Jenkins UI: jobs, builds, console output",
                    "Managing plugins: install, update, restart",
                    "Jenkins CLI for scripted administration",
                    "Backup and restore Jenkins configuration",
                    "User management and role-based access control",
                ],
                "project": "Install Jenkins, configure GitHub integration, and set up a triggered build on every push",
                "resources": [
                    {"title": "Jenkins Official Docs", "url": "https://www.jenkins.io/doc/"},
                ],
            },
            {
                "id": "jenkins-pipelines",
                "title": "Pipelines as Code (Jenkinsfile)",
                "topics": [
                    "Declarative vs scripted Jenkinsfile syntax",
                    "Pipeline stages: checkout, build, test, publish",
                    "Multi-stage pipelines with parallel execution",
                    "Environment variables and credentials management",
                    "Building a full CI pipeline with automated tests",
                    "Building a CD pipeline: build image, push to registry, deploy",
                ],
                "project": "Build a full CI/CD pipeline: code push triggers test, Docker build, push to DockerHub, and deploy",
                "resources": [],
            },
        ],
    },
    {
        "phase": "04",
        "title": "Docker & Containers",
        "duration": "2-3 weeks",
        "color": "#FFD700",
        "description": "Package once, run anywhere. Own the container.",
        "modules": [
            {
                "id": "docker-fundamentals",
                "title": "Docker Fundamentals",
                "topics": [
                    "Docker architecture: daemon, client, registry",
                    "Core commands: docker run, ps, stop, rm, exec, logs",
                    "Image vs container: the layered filesystem",
                    "Interactive containers vs detached mode (-it vs -d)",
                    "Port mapping and environment variables (-p, -e flags)",
                    "Container lifecycle management",
                ],
                "project": "Run a multi-container application (web + database) using docker run commands",
                "resources": [
                    {"title": "Docker Official Docs", "url": "https://docs.docker.com/"},
                ],
            },
            {
                "id": "docker-images",
                "title": "Docker Images & Dockerfile",
                "topics": [
                    "Writing a Dockerfile: FROM, RUN, COPY, EXPOSE, CMD, ENTRYPOINT",
                    "CMD vs ENTRYPOINT: when to use each",
                    "Multi-stage builds for lean production images",
                    "Image tagging and versioning strategy",
                    "Pushing to Docker Hub and private registries (ECR, GCR)",
                    "Image security scanning basics",
                ],
                "project": "Containerize a full-stack app with a multi-stage Dockerfile, push to Docker Hub",
                "resources": [],
            },
            {
                "id": "docker-storage-networking",
                "title": "Storage, Networking & Compose",
                "topics": [
                    "Docker volumes vs bind mounts vs tmpfs",
                    "Volume commands: create, inspect, rm",
                    "Docker networking modes: bridge, host, none, custom",
                    "Container-to-container communication via DNS",
                    "Docker Compose: services, networks, volumes in docker-compose.yml",
                    "Docker Compose commands: up, down, build, logs, scale",
                ],
                "project": "Define a full-stack app (web + API + database + cache) in a Docker Compose file",
                "resources": [],
            },
        ],
    },
    {
        "phase": "05",
        "title": "Kubernetes",
        "duration": "3-4 weeks",
        "color": "#BF5FFF",
        "description": "Orchestrate containers at scale. The industry standard.",
        "modules": [
            {
                "id": "k8s-architecture",
                "title": "Kubernetes Architecture & Core Objects",
                "topics": [
                    "Cluster architecture: control plane, worker nodes, etcd",
                    "kubectl basics: get, describe, apply, delete, logs, exec",
                    "YAML manifests: apiVersion, kind, metadata, spec",
                    "Pods: single vs multi-container, lifecycle phases",
                    "Namespaces: isolation, resource quotas, default vs custom",
                    "Minikube and kubeadm for local development",
                ],
                "project": "Deploy a containerized app as a Pod using a YAML manifest, inspect and debug it with kubectl",
                "resources": [
                    {"title": "Kubernetes Official Docs", "url": "https://kubernetes.io/docs/home/"},
                ],
            },
            {
                "id": "k8s-workloads",
                "title": "ReplicaSets, Deployments & Rollouts",
                "topics": [
                    "ReplicationControllers vs ReplicaSets: selectors and scaling",
                    "Deployments: declarative updates, rollout strategy",
                    "Rolling updates and rollbacks: kubectl rollout",
                    "Scaling: kubectl scale, HorizontalPodAutoscaler basics",
                    "ConfigMaps and Secrets: injecting config into pods",
                    "Resource requests and limits",
                ],
                "project": "Deploy an app with a Deployment, perform a rolling update to a new image version, then rollback",
                "resources": [],
            },
            {
                "id": "k8s-services",
                "title": "Services, Networking & Microservices",
                "topics": [
                    "Service types: ClusterIP, NodePort, LoadBalancer",
                    "How Kubernetes DNS resolves service names",
                    "Deploying a multi-tier voting app on Kubernetes",
                    "Connecting frontend, backend and database pods via Services",
                    "Using Deployments for all components of a microservices app",
                    "Basics of Ingress for HTTP routing",
                ],
                "project": "Deploy the full voting app (vote, result, worker, Redis, Postgres) on Kubernetes end-to-end",
                "resources": [],
            },
        ],
    },
    {
        "phase": "06",
        "title": "Ansible & Terraform",
        "duration": "3-4 weeks",
        "color": "#FF2D7A",
        "description": "Infrastructure is code. Automate everything you build.",
        "modules": [
            {
                "id": "ansible-basics",
                "title": "Ansible Configuration Management",
                "topics": [
                    "Ansible architecture: control node, managed nodes, agentless SSH",
                    "Inventory files: static, dynamic, groups, variables",
                    "Ad-hoc commands: ansible -m ping, command, shell",
                    "Playbooks: plays, tasks, handlers, notify",
                    "Core modules: copy, file, yum/apt, service, template, user",
                    "Variables, facts and Jinja2 templating",
                ],
                "project": "Write an Ansible playbook to provision a web server: install Nginx, deploy app, configure firewall",
                "resources": [
                    {"title": "Ansible Docs", "url": "https://docs.ansible.com/"},
                ],
            },
            {
                "id": "ansible-advanced",
                "title": "Ansible Roles, Loops & Conditionals",
                "topics": [
                    "Conditionals: when, failed_when, changed_when",
                    "Loops: loop, with_items, with_dict, with_fileglob",
                    "Ansible roles: directory structure, defaults, tasks, handlers",
                    "Ansible Galaxy: downloading and using community roles",
                    "Organizing large playbooks with includes and imports",
                ],
                "project": "Refactor a playbook into reusable Ansible roles and publish to Ansible Galaxy",
                "resources": [],
            },
            {
                "id": "terraform-iac",
                "title": "Terraform Infrastructure as Code",
                "topics": [
                    "HCL syntax: resources, providers, variables, outputs",
                    "Core workflow: terraform init, plan, apply, destroy",
                    "Input variables, variable blocks and .tfvars files",
                    "Resource attributes, dependencies and output variables",
                    "Terraform state: local vs remote backends (S3 + DynamoDB)",
                    "Lifecycle rules, datasources, count and for_each meta-arguments",
                    "Mutable vs immutable infrastructure",
                    "Version constraints for providers and modules",
                ],
                "project": "Provision a full AWS environment with Terraform: VPC, subnets, EC2 instances, security groups",
                "resources": [
                    {"title": "Terraform Docs", "url": "https://developer.hashicorp.com/terraform/docs"},
                ],
            },
        ],
    },
    {
        "phase": "07",
        "title": "AI Infrastructure: Deploying LLMs",
        "duration": "2-3 weeks",
        "color": "#FFD700",
        "description": "Run large language models yourself, on any cloud or your own hardware.",
        "modules": [
            {
                "id": "llm-serving-fundamentals",
                "title": "LLM Serving Fundamentals",
                "topics": [
                    "Hosted model APIs vs self-hosted open-weight models: when each makes sense",
                    "Why teams self-host: data privacy, steady-volume cost, customization, control",
                    "GPU memory math: roughly 2 bytes per parameter at 16-bit, plus KV cache",
                    "Choosing a GPU: T4, A10G, L4 and larger cards; matching model size to VRAM",
                    "Inference servers: vLLM's OpenAI-compatible API, batching and the KV cache",
                    "Model sources and licensing: Hugging Face, gated models, access tokens",
                ],
                "project": "Size three open models (1.5B, 7B, 70B) against T4, L4 and A100 GPUs and justify which fits where",
                "resources": [
                    {"title": "vLLM Documentation", "url": "https://docs.vllm.ai/"},
                ],
            },
            {
                "id": "llm-cloud-gpu-deploy",
                "title": "Deploying LLMs on AWS, Azure and GCP",
                "topics": [
                    "GPU quotas: why new accounts start at zero and how to request capacity",
                    "GPU-ready images: AWS Deep Learning AMI, Azure NVIDIA driver extension, GCP Deep Learning VM",
                    "Provision-then-configure in one step with user_data, custom scripts and startup scripts",
                    "Locking down the API: security groups, NSGs and firewall rules scoped to one CIDR",
                    "Verifying a deployment: health checks, the /v1/models endpoint, API keys",
                    "Teardown discipline: GPUs bill by the hour whether or not anyone is using them",
                ],
                "project": "Deploy a small open model on one GPU VM in each of AWS, Azure and GCP using the DevOps Agent AI/ML workflows, then compare setup time and cost",
                "resources": [
                    {"title": "AWS Deep Learning AMIs", "url": "https://docs.aws.amazon.com/dlami/latest/devguide/"},
                ],
            },
            {
                "id": "llm-kubernetes-onprem",
                "title": "LLMs on Kubernetes: Cloud and On-Prem",
                "topics": [
                    "GPU node groups and node pools on EKS, AKS and GKE",
                    "The NVIDIA driver, container toolkit and device plugin: who installs what",
                    "Requesting GPUs in a pod spec with resources.limits nvidia.com/gpu",
                    "Shared memory, readiness probes and storing API keys in Secrets",
                    "On-prem specifics: bare-metal GPU nodes, air-gapped clusters, pre-staged model weights",
                    "The NVIDIA GPU Operator for managing drivers at fleet scale",
                ],
                "project": "Run vLLM on a Kubernetes cluster with one GPU node: install the device plugin, deploy, and reach the API through a port-forward",
                "resources": [
                    {"title": "NVIDIA k8s-device-plugin", "url": "https://github.com/NVIDIA/k8s-device-plugin"},
                ],
            },
            {
                "id": "llm-production-ops",
                "title": "Operating LLMs at Scale",
                "topics": [
                    "AI economics: cost per million tokens for self-hosted vs API pricing",
                    "Intelligent model routing: sending easy requests to small models",
                    "Autoscaling GPU workloads on queue depth instead of CPU",
                    "Observability: vLLM metrics, GPU utilization, latency and tokens per second",
                    "Governance: access control, request logging, data residency and audit trails",
                    "Production hardening: TLS, private networking, pinned images, rollouts",
                ],
                "project": "Measure tokens/sec under concurrent load on a self-hosted model and write a one-page cost comparison against a hosted API",
                "resources": [],
            },
        ],
    },
]

CERTIFICATIONS = [
    {"name": "AWS Solutions Architect Associate", "level": "Foundational", "color": "#FF6B35"},
    {"name": "Certified Kubernetes Admin (CKA)", "level": "Intermediate", "color": "#BF5FFF"},
    {"name": "Certified Kubernetes App Dev (CKAD)", "level": "Intermediate", "color": "#00C2FF"},
    {"name": "HashiCorp Terraform Associate", "level": "Foundational", "color": "#FF2D7A"},
    {"name": "AWS DevOps Engineer Professional", "level": "Advanced", "color": "#FFD700"},
    {"name": "Red Hat Certified Engineer (RHCE)", "level": "Advanced", "color": "#00FFB2"},
]

TOTAL_MODULES = sum(len(p["modules"]) for p in CURRICULUM)
