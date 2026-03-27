server {
    listen 80;
    server_name dev.procollab.ru;
    server_tokens off;

    location ^~ /.well-known/acme-challenge/ {
        root /var/www/certbot;
        default_type "text/plain";
        try_files $uri =404;
    }

    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl;
    server_name dev.procollab.ru;
    server_tokens off;

    ssl_certificate     /etc/letsencrypt/live/dev.procollab.ru-0001/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/dev.procollab.ru-0001/privkey.pem;

    location / {
        include /etc/nginx/procollab/includes/proxy_app.inc;
    }
}
