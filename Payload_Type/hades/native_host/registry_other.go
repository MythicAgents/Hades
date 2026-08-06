//go:build !windows

package main

import "errors"

func registryInstall(_ string) error {
	return errors.New("registry not available on this OS")
}

func registryUninstall() error {
	return errors.New("registry not available on this OS")
}
