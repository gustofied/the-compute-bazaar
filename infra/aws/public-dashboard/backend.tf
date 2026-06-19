terraform {
  backend "s3" {
    bucket       = "compute-bazaar-852794024525-eu-west-3-an"
    key          = "terraform/public-dashboard/terraform.tfstate"
    region       = "eu-west-3"
    encrypt      = true
    use_lockfile = true
  }
}
