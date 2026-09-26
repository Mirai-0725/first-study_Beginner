# ===== EC2 =====

# Ubuntu Server 24.04 LTS(Arm版。t4g インスタンスはArm)の最新AMI
data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-arm64-server-*"]
  }

  filter {
    name   = "architecture"
    values = ["arm64"]
  }
}

# ----- IAMロール(SSMでの接続と、DBパスワードの読み取りに使う) -----

resource "aws_iam_role" "app" {
  name = "${var.project}-app-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

# SSM セッションマネージャーで EC2 に接続できるようにする(SSHの代わり)
resource "aws_iam_role_policy_attachment" "app_ssm" {
  role       = aws_iam_role.app.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# DBのパスワードのパラメータだけを読めるようにする
resource "aws_iam_role_policy" "app_read_db_password" {
  name = "read-db-password"
  role = aws_iam_role.app.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "ssm:GetParameter"
      Resource = aws_ssm_parameter.db_password.arn
    }]
  })
}

resource "aws_iam_instance_profile" "app" {
  name = "${var.project}-app-profile"
  role = aws_iam_role.app.name
}

# ----- Elastic IP(停止・起動してもアドレスが変わらないようにする) -----

resource "aws_eip" "app" {
  domain = "vpc"

  tags = { Name = "${var.project}-eip" }
}

resource "aws_eip_association" "app" {
  instance_id   = aws_instance.app.id
  allocation_id = aws_eip.app.id
}

# ----- インスタンス -----

resource "aws_instance" "app" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.instance_type
  subnet_id              = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.app.id]
  iam_instance_profile   = aws_iam_instance_profile.app.name

  associate_public_ip_address = false

  # 初回起動時に、アプリのインストールから起動までを自動で行う
  user_data = templatefile("${path.module}/templates/user_data.sh.tftpl", {
    region            = var.region
    public_ip         = aws_eip.app.public_ip
    repository_url    = var.repository_url
    repository_branch = var.repository_branch
    db_host           = aws_db_instance.main.address
    db_port           = aws_db_instance.main.port
    db_name           = aws_db_instance.main.db_name
    db_user           = aws_db_instance.main.username
    db_password_param = aws_ssm_parameter.db_password.name
  })
  user_data_replace_on_change = true

  # インスタンスメタデータは IMDSv2(トークン必須)のみ許可する
  metadata_options {
    http_tokens = "required"
  }

  root_block_device {
    volume_size = 8
    volume_type = "gp3"
    encrypted   = true
  }

  tags = { Name = "${var.project}-app" }
}
