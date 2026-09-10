# W6·B deploy stack (docs/w6b-decisions.md) — one flat stack, no module nesting.
# Region is ap-south-1 (Mumbai) per owner decision, overriding the grill
# session's us-east-1 placeholder.
terraform {
  required_version = ">= 1.10" # S3 backend lockfile (decision #10)

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.90"
    }
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.7"
    }
  }
}

provider "aws" {
  region = var.region
}

# Cloudflare is DNS + edge TLS termination (decision #2). The zone itself is
# created once in the Cloudflare dashboard (owner step); Terraform only
# manages the records inside it. Token via CLOUDFLARE_API_TOKEN env var.
provider "cloudflare" {}
