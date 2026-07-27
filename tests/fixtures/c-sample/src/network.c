#include "network.h"

#define NETWORK_DEFAULT_PORT 9000

static int network_ready = 0;

int network_init(const network_config_t *config) {
  if (config == 0) return -1;
  network_ready = config->port == 0 ? NETWORK_DEFAULT_PORT : config->port;
  return network_ready ? 0 : -1;
}

void network_shutdown(void) {
  network_ready = 0;
}

