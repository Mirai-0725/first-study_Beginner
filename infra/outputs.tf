output "app_url" {
  description = "アプリのURL(allowed_cidr のIPアドレスからのみアクセスできる)"
  value       = "http://${aws_eip.app.public_ip}/"
}

output "instance_id" {
  description = "EC2のインスタンスID(SSMで接続するときに使う)"
  value       = aws_instance.app.id
}

output "db_endpoint" {
  description = "RDSの接続先(EC2からのみ接続できる)"
  value       = aws_db_instance.main.address
}
