docker compose down nextcloud-aio-mastercontainer &&\
docker ps -a --filter "name=^/nextcloud" -q | xargs -r docker stop &&\
docker ps -a --filter "name=^/nextcloud" -q | xargs -r docker rm &&\
docker volume ls -q | grep nextcloud | xargs -r docker volume rm &&\
docker network rm nextcloud-aio &&\
sudo find /mnt/ncdata/ -type f -delete &&\
sudo find /mnt/ncdata/ -type d -delete