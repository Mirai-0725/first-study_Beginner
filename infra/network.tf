# ===== VPC =====
# NATゲートウェイは有料のため作らない(RDSはインターネットへ出る必要がない)

data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  # RDSのサブネットグループには2つ以上のAZが必要
  azs = slice(data.aws_availability_zones.available.names, 0, 2)
}

resource "aws_vpc" "main" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = { Name = "${var.project}-vpc" }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = { Name = "${var.project}-igw" }
}

# ----- パブリックサブネット(EC2を配置) -----

resource "aws_subnet" "public" {
  vpc_id            = aws_vpc.main.id
  cidr_block        = "10.0.1.0/24"
  availability_zone = local.azs[0]

  # 自動のパブリックIPは付けず、Elastic IP を付ける(停止・起動してもIPが変わらないようにする)
  map_public_ip_on_launch = false

  tags = { Name = "${var.project}-public-a" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = { Name = "${var.project}-public-rt" }
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

# ----- プライベートサブネット(RDSを配置) -----
# インターネットへの経路を持たないルートテーブルを使う

resource "aws_subnet" "private" {
  count = 2

  vpc_id            = aws_vpc.main.id
  cidr_block        = "10.0.${11 + count.index}.0/24"
  availability_zone = local.azs[count.index]

  tags = { Name = "${var.project}-private-${count.index + 1}" }
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id

  tags = { Name = "${var.project}-private-rt" }
}

resource "aws_route_table_association" "private" {
  count = 2

  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}
