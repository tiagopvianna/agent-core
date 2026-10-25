import AppKit
import Foundation

guard CommandLine.arguments.count == 3 else {
    fputs("Usage: rasterize_svg.swift <input.svg> <output.png>\n", stderr)
    exit(2)
}

let inputURL = URL(fileURLWithPath: CommandLine.arguments[1])
let outputURL = URL(fileURLWithPath: CommandLine.arguments[2])

guard let image = NSImage(contentsOf: inputURL) else {
    fputs("Unable to load SVG: \(inputURL.path)\n", stderr)
    exit(1)
}

let sourceSize = image.size
let scale = 2
let targetWidth = max(Int(sourceSize.width) * scale, 1)
let targetHeight = max(Int(sourceSize.height) * scale, 1)
guard let bitmap = NSBitmapImageRep(
    bitmapDataPlanes: nil,
    pixelsWide: targetWidth,
    pixelsHigh: targetHeight,
    bitsPerSample: 8,
    samplesPerPixel: 4,
    hasAlpha: true,
    isPlanar: false,
    colorSpaceName: .deviceRGB,
    bitmapFormat: [],
    bytesPerRow: 0,
    bitsPerPixel: 0
) else {
    fputs("Unable to allocate PNG bitmap.\n", stderr)
    exit(1)
}

guard let context = NSGraphicsContext(bitmapImageRep: bitmap) else {
    fputs("Unable to create drawing context.\n", stderr)
    exit(1)
}

NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = context
image.draw(in: NSRect(x: 0, y: 0, width: CGFloat(targetWidth), height: CGFloat(targetHeight)))
context.flushGraphics()
NSGraphicsContext.restoreGraphicsState()

guard let png = bitmap.representation(using: .png, properties: [:]) else {
    fputs("Unable to encode PNG.\n", stderr)
    exit(1)
}

do {
    try png.write(to: outputURL)
} catch {
    fputs("Unable to write PNG: \(error)\n", stderr)
    exit(1)
}

