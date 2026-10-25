#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
bool raw_fake_send(int fd, const uint8_t *payload, size_t size, uint8_t ttl, bool md5);
bool raw_fake_supported(void);
