#!/bin/bash
set -e

echo "=============================="
echo " RTC FULL BOOTSTRAP START"
echo "=============================="

./scripts/reset.sh
./scripts/load-images.sh
./scripts/deploy.sh

echo "=============================="
echo " RTC SYSTEM READY"
echo "=============================="

kubectl get pods -n rtc -o wide