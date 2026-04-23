server {
    listen 80;
    listen [::]:80;
    server_name api.procollab.ru;
    server_tokens off;

    location ^~ /.well-known/acme-challenge/ {
        root /var/www/html;
        default_type "text/plain";
        try_files $uri =404;
    }

    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name api.procollab.ru;
    server_tokens off;

    ssl_certificate     /etc/letsencrypt/live/api.procollab.ru-0001/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.procollab.ru-0001/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;

    client_max_body_size 100M;

    location / {
        include /etc/nginx/procollab/includes/proxy_app.inc;
    }
}
