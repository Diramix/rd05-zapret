# Zapret для Xiaomi RD05

Готовая настройка обхода DPI для роутера **Xiaomi Mi Router 4A Gigabit (RD05)**.

> [!IMPORTANT]
> Перед установкой необходимо получить root-доступ к роутеру с помощью [xmir-patcher](https://github.com/openwrt-xiaomi/xmir-patcher).

## Запуск

```bash
git clone https://github.com/Diramix/rd05-zapret
cd rd05-zapret
python3 service.py
```

После запуска введите данные SSH для подключения к роутеру и выберите нужное действие в меню.

После установки TG WS Telegram MTProto-прокси доступен на порту `1443` LAN-адреса роутера. Добавьте его в настройках Telegram через ссылку (замените адрес, если LAN-адрес роутера отличается):

```
https://t.me/proxy?server=192.168.31.1&port=1443&secret=ddf37ff59d5946e9c1c7670a3710a099fe
```
