# S3 backend with native lockfile (decision #10): Terraform >= 1.10, no
# DynamoDB lock table. The bucket is created ONCE outside Terraform and
# deliberately survives teardown so state outlives the stack and the
# destroy → redeploy cycle is safe:
#
#   aws s3api create-bucket \
#     --bucket cci-tfstate-ap-south-1 \
#     --region ap-south-1 --create-bucket-configuration Location=ap-south-1
#   aws s3api put-bucket-versioning \
#     --bucket cci-tfstate-ap-south-1 \
#     --versioning-configuration Status=Enabled
#
# terraform init picks up the block above as-is (values are pinned here);
# CI reads outputs from this same state.
terraform {
  backend "s3" {
    bucket       = "cci-tfstate-ap-south-1"
    key          = "w6b/terraform.tfstate"
    region       = "ap-south-1"
    use_lockfile = true
  }
}
