namespace AutoFollow.Core;

internal static class MouseMessageCoordinates
{
    // WM_LBUTTON* stores signed client coordinates in two 16-bit words.
    internal static bool TryPack(int x, int y, int width, int height, out IntPtr lParam)
    {
        lParam = IntPtr.Zero;
        if (width <= 0 || height <= 0 || x < 0 || y < 0 || x >= width || y >= height ||
            x > short.MaxValue || y > short.MaxValue)
            return false;

        lParam = new IntPtr((y << 16) | (x & 0xFFFF));
        return true;
    }
}
