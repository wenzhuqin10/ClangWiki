#include "network.h"

int main(void) {
  network_config_t config = {"127.0.0.1", 9000};
  return network_init(&config);
}

