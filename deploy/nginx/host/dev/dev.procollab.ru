server {
    listen 80;
    server_name dev.procollab.ru;
    server_tokens off;
    client_max_body_size 100M;

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
    root /home/front/app;
    index index.html;

    ssl_certificate     /etc/letsencrypt/live/dev.procollab.ru-0001/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/dev.procollab.ru-0001/privkey.pem;

    client_max_body_size 100M;

    # Angular auth pages share /auth with Django API endpoints. Only page reads
    # go to the SPA; POST password reset requests must still reach Django.
    # Keep this allowlist before the broader API regex (first regex wins).
    location ~ ^/auth(/(login|register|verification(/email)?|reset_password(/(send_email|confirm))?))?/?$ {
        if ($request_method ~ ^(GET|HEAD)$) {
            rewrite ^ /index.html last;
        }
        include /etc/nginx/procollab/includes/proxy_app.inc;
    }

    location ~ ^/(admin|api-auth|files|industries|news|projects|vacancies|core|invites|solution-invitations|solution-form-templates|auth|chats|events|programs|courses|rate-project|evaluation|feed|api|anymail|ws)(/|$) {
        include /etc/nginx/procollab/includes/proxy_app.inc;
    }

    location ~ ^/(swagger(\.json|\.yaml)?|swagger/|redoc/?)$ {
        include /etc/nginx/procollab/includes/proxy_app.inc;
    }

    location ^~ /static/admin/ {
        include /etc/nginx/procollab/includes/proxy_app.inc;
    }

    location ^~ /static/drf-yasg/ {
        include /etc/nginx/procollab/includes/proxy_app.inc;
    }

    location ^~ /static/rest_framework/ {
        include /etc/nginx/procollab/includes/proxy_app.inc;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
