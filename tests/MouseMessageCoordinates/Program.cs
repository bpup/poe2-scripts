using AutoFollow.Core;

static void Check(bool expected, int x, int y, int width, int height, int packed = 0)
{
    var accepted = MouseMessageCoordinates.TryPack(x, y, width, height, out var actual);
    if (accepted != expected || (accepted && actual.ToInt64() != (uint)packed))
        throw new Exception($"Unexpected mouse message for ({x}, {y}) in {width}x{height}");
}

Check(true, 0, 0, 1920, 1080);
Check(true, 120, 45, 1920, 1080, (45 << 16) | 120);
Check(true, 1919, 1079, 1920, 1080, (1079 << 16) | 1919);
Check(false, -1, 0, 1920, 1080);
Check(false, 1920, 0, 1920, 1080);
Check(false, 0, 1080, 1920, 1080);
Check(false, 0, 0, 0, 1080);
Check(false, 32768, 0, 40000, 1080);
Console.WriteLine("Mouse message coordinate checks passed.");
