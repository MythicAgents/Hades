//go:build windows

package main

import (
	"fmt"
	"golang.org/x/sys/windows/registry"
)

const regKeyPath = `SOFTWARE\Google\Chrome\NativeMessagingHosts\` + hostName

func registryInstall(manifestPath string) error {
	k, _, err := registry.CreateKey(registry.CURRENT_USER, regKeyPath, registry.SET_VALUE)
	if err != nil {
		return fmt.Errorf("CreateKey: %w", err)
	}
	defer k.Close()
	return k.SetStringValue("", manifestPath)
}

func registryUninstall() error {
	return registry.DeleteKey(registry.CURRENT_USER, regKeyPath)
}
