#!/bin/bash

# In order to use this script
# machine should have installed:
# - git
# - node^16

cd ..
git clone https://github.com/PROCOLLAB-github/emails.git
cd emails || exit

npm ci
npm run build

cd ..
cp -R ./emails/dist ./email
rm -rf ./emails