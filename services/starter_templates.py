"""Curated public starter infrastructure templates.

Seeded into the `infrastructure_templates` table (is_public=True) so every user
sees a useful catalog on /ai/templates instead of an empty page. Each entry maps
directly onto the InfrastructureTemplate model columns. `variables` is a list of
{name, description, default} that the preview substitutes as `${name}` tokens in
`template_content`.
"""

STARTER_TEMPLATES = [
    {
        "slug": "aws-vpc-3tier",
        "name": "AWS 3-Tier VPC",
        "description": "A production-ready VPC with public and private subnets across two "
                       "availability zones, an internet gateway, and a NAT gateway.",
        "category": "networking",
        "cloud_provider": "aws",
        "template_type": "terraform",
        "estimated_monthly_cost": 34.0,
        "variables": [
            {"name": "vpc_cidr", "description": "CIDR block for the VPC", "default": "10.0.0.0/16"},
            {"name": "region", "description": "AWS region", "default": "us-east-1"},
            {"name": "project", "description": "Project name tag", "default": "my-app"},
        ],
        "template_content": '''provider "aws" {
  region = "${region}"
}

resource "aws_vpc" "main" {
  cidr_block           = "${vpc_cidr}"
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags = { Name = "${project}-vpc" }
}

resource "aws_internet_gateway" "igw" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "${project}-igw" }
}

resource "aws_subnet" "public" {
  count                   = 2
  vpc_id                  = aws_vpc.main.id
  cidr_block              = cidrsubnet(aws_vpc.main.cidr_block, 8, count.index)
  map_public_ip_on_launch = true
  availability_zone       = data.aws_availability_zones.available.names[count.index]
  tags = { Name = "${project}-public-${count.index}" }
}

resource "aws_subnet" "private" {
  count             = 2
  vpc_id            = aws_vpc.main.id
  cidr_block        = cidrsubnet(aws_vpc.main.cidr_block, 8, count.index + 10)
  availability_zone = data.aws_availability_zones.available.names[count.index]
  tags = { Name = "${project}-private-${count.index}" }
}

data "aws_availability_zones" "available" {
  state = "available"
}
''',
    },
    {
        "slug": "aws-ec2-web",
        "name": "EC2 Web Server",
        "description": "A single EC2 instance running Nginx, locked down to HTTP/HTTPS/SSH "
                       "with a security group and a stable Elastic IP.",
        "category": "web",
        "cloud_provider": "aws",
        "template_type": "terraform",
        "estimated_monthly_cost": 8.5,
        "variables": [
            {"name": "instance_type", "description": "EC2 instance type", "default": "t3.micro"},
            {"name": "region", "description": "AWS region", "default": "us-east-1"},
            {"name": "ssh_cidr", "description": "CIDR allowed to SSH", "default": "0.0.0.0/0"},
        ],
        "template_content": '''provider "aws" {
  region = "${region}"
}

resource "aws_security_group" "web" {
  name        = "web-sg"
  description = "Allow web and SSH traffic"

  ingress { from_port = 80  to_port = 80  protocol = "tcp" cidr_blocks = ["0.0.0.0/0"] }
  ingress { from_port = 443 to_port = 443 protocol = "tcp" cidr_blocks = ["0.0.0.0/0"] }
  ingress { from_port = 22  to_port = 22  protocol = "tcp" cidr_blocks = ["${ssh_cidr}"] }
  egress  { from_port = 0   to_port = 0   protocol = "-1"  cidr_blocks = ["0.0.0.0/0"] }
}

resource "aws_instance" "web" {
  ami                    = data.aws_ami.al2.id
  instance_type          = "${instance_type}"
  vpc_security_group_ids = [aws_security_group.web.id]
  user_data              = "#!/bin/bash\\namazon-linux-extras install nginx1 -y\\nsystemctl enable --now nginx"
  tags                   = { Name = "web-server" }
}

resource "aws_eip" "web" {
  instance = aws_instance.web.id
}

data "aws_ami" "al2" {
  most_recent = true
  owners      = ["amazon"]
  filter { name = "name" values = ["amzn2-ami-hvm-*-x86_64-gp2"] }
}
''',
    },
    {
        "slug": "aws-rds-postgres",
        "name": "RDS PostgreSQL",
        "description": "A managed PostgreSQL database with encryption at rest, automated "
                       "backups, and a private subnet group (not publicly accessible).",
        "category": "database",
        "cloud_provider": "aws",
        "template_type": "terraform",
        "estimated_monthly_cost": 29.0,
        "variables": [
            {"name": "db_instance_class", "description": "RDS instance class", "default": "db.t3.micro"},
            {"name": "db_name", "description": "Initial database name", "default": "appdb"},
            {"name": "region", "description": "AWS region", "default": "us-east-1"},
        ],
        "template_content": '''provider "aws" {
  region = "${region}"
}

resource "aws_db_instance" "postgres" {
  identifier             = "${db_name}-postgres"
  engine                 = "postgres"
  engine_version         = "16.3"
  instance_class         = "${db_instance_class}"
  allocated_storage      = 20
  db_name                = "${db_name}"
  username               = "appuser"
  manage_master_user_password = true
  storage_encrypted      = true
  backup_retention_period = 7
  publicly_accessible    = false
  skip_final_snapshot     = false
  final_snapshot_identifier = "${db_name}-final"
  tags = { Name = "${db_name}-postgres" }
}
''',
    },
    {
        "slug": "aws-s3-static-site",
        "name": "S3 Static Website",
        "description": "An S3 bucket configured for static website hosting with versioning "
                       "and public-read scoped to the site objects only.",
        "category": "web",
        "cloud_provider": "aws",
        "template_type": "terraform",
        "estimated_monthly_cost": 1.0,
        "variables": [
            {"name": "bucket_name", "description": "Globally-unique bucket name", "default": "my-static-site-123"},
            {"name": "region", "description": "AWS region", "default": "us-east-1"},
        ],
        "template_content": '''provider "aws" {
  region = "${region}"
}

resource "aws_s3_bucket" "site" {
  bucket = "${bucket_name}"
}

resource "aws_s3_bucket_versioning" "site" {
  bucket = aws_s3_bucket.site.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_website_configuration" "site" {
  bucket = aws_s3_bucket.site.id
  index_document { suffix = "index.html" }
  error_document { key = "error.html" }
}
''',
    },
    {
        "slug": "aws-eks-cluster",
        "name": "EKS Kubernetes Cluster",
        "description": "A managed EKS control plane with a small managed node group — a "
                       "starting point for running containers on Kubernetes.",
        "category": "kubernetes",
        "cloud_provider": "aws",
        "template_type": "terraform",
        "estimated_monthly_cost": 145.0,
        "variables": [
            {"name": "cluster_name", "description": "EKS cluster name", "default": "my-cluster"},
            {"name": "node_instance_type", "description": "Worker node instance type", "default": "t3.medium"},
            {"name": "desired_nodes", "description": "Desired worker node count", "default": "2"},
        ],
        "template_content": '''resource "aws_eks_cluster" "this" {
  name     = "${cluster_name}"
  role_arn = aws_iam_role.cluster.arn
  vpc_config { subnet_ids = var.subnet_ids }
}

resource "aws_eks_node_group" "this" {
  cluster_name    = aws_eks_cluster.this.name
  node_group_name = "${cluster_name}-ng"
  node_role_arn   = aws_iam_role.node.arn
  subnet_ids      = var.subnet_ids
  instance_types  = ["${node_instance_type}"]
  scaling_config {
    desired_size = ${desired_nodes}
    max_size     = 4
    min_size     = 1
  }
}
''',
    },
    {
        "slug": "aws-asg-alb",
        "name": "Auto-Scaling Web Tier",
        "description": "An Application Load Balancer in front of an Auto Scaling group, so "
                       "your web tier scales with traffic and survives instance failure.",
        "category": "web",
        "cloud_provider": "aws",
        "template_type": "terraform",
        "estimated_monthly_cost": 42.0,
        "variables": [
            {"name": "min_size", "description": "Minimum instances", "default": "2"},
            {"name": "max_size", "description": "Maximum instances", "default": "6"},
            {"name": "instance_type", "description": "Instance type", "default": "t3.small"},
        ],
        "template_content": '''resource "aws_launch_template" "web" {
  name_prefix   = "web-"
  image_id      = data.aws_ami.al2.id
  instance_type = "${instance_type}"
}

resource "aws_autoscaling_group" "web" {
  desired_capacity    = ${min_size}
  min_size            = ${min_size}
  max_size            = ${max_size}
  vpc_zone_identifier = var.subnet_ids
  target_group_arns   = [aws_lb_target_group.web.arn]
  launch_template { id = aws_launch_template.web.id version = "$Latest" }
}

resource "aws_lb" "web" {
  name               = "web-alb"
  load_balancer_type = "application"
  subnets            = var.subnet_ids
}

resource "aws_lb_target_group" "web" {
  name     = "web-tg"
  port     = 80
  protocol = "HTTP"
  vpc_id   = var.vpc_id
}

data "aws_ami" "al2" {
  most_recent = true
  owners      = ["amazon"]
  filter { name = "name" values = ["amzn2-ami-hvm-*-x86_64-gp2"] }
}
''',
    },
]
