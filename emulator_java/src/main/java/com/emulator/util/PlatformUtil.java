package com.emulator.util;

public class PlatformUtil {
    private static final boolean WINDOWS = System.getProperty("os.name", "")
            .toLowerCase().contains("win");

    public static boolean isWindows() { return WINDOWS; }
    public static boolean isLinux() { return !WINDOWS; }
}
