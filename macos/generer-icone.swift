// Génère l'icône de Reunion.app : squircle sombre + micro, aux tailles attendues
// par iconutil. Usage : swift generer-icone.swift <dossier.iconset>

import AppKit
import Foundation

let outDir = CommandLine.arguments.count > 1
    ? CommandLine.arguments[1]
    : NSTemporaryDirectory() + "reunion.iconset"
try? FileManager.default.createDirectory(atPath: outDir, withIntermediateDirectories: true)

func drawIcon(size: CGFloat) -> NSImage {
    let image = NSImage(size: NSSize(width: size, height: size))
    image.lockFocus()
    defer { image.unlockFocus() }

    guard let ctx = NSGraphicsContext.current?.cgContext else { return image }
    ctx.setAllowsAntialiasing(true)

    // Marge : les icônes du Dock ne remplissent pas leur cadre, sinon elles
    // paraissent plus grosses que les icônes système voisines.
    let inset = size * 0.055
    let rect = CGRect(x: inset, y: inset, width: size - 2 * inset, height: size - 2 * inset)
    let radius = rect.width * 0.235          // proportion du squircle macOS

    let path = NSBezierPath(roundedRect: rect, xRadius: radius, yRadius: radius)
    path.addClip()

    NSGradient(colors: [
        NSColor(calibratedRed: 0.24, green: 0.26, blue: 0.32, alpha: 1),
        NSColor(calibratedRed: 0.10, green: 0.11, blue: 0.14, alpha: 1),
    ])?.draw(in: rect, angle: -90)

    // Liseré clair sur le bord haut : donne du relief comme les icônes natives.
    NSColor(white: 1, alpha: 0.13).setStroke()
    let edge = NSBezierPath(roundedRect: rect.insetBy(dx: size * 0.004, dy: size * 0.004),
                            xRadius: radius, yRadius: radius)
    edge.lineWidth = max(1, size * 0.008)
    edge.stroke()

    // Micro. L'ordre compte : l'arceau se dessine avant la capsule pour passer
    // derrière elle, comme sur un vrai micro sur pied.
    let cx = rect.midX
    let W = rect.width, H = rect.height
    let chrome = NSColor(white: 0.93, alpha: 1)

    let capsuleW = W * 0.215
    let capsuleH = H * 0.355
    let capsule = CGRect(x: cx - capsuleW / 2, y: rect.minY + H * 0.455,
                         width: capsuleW, height: capsuleH)

    let arcR = W * 0.205
    let arcCY = capsule.minY + H * 0.105
    let arcBottom = arcCY - arcR

    let arc = NSBezierPath()
    arc.appendArc(withCenter: CGPoint(x: cx, y: arcCY),
                  radius: arcR, startAngle: 195, endAngle: 345, clockwise: true)
    chrome.setStroke()
    arc.lineWidth = max(1, W * 0.052)
    arc.lineCapStyle = .round
    arc.stroke()

    NSColor(calibratedRed: 0.96, green: 0.35, blue: 0.32, alpha: 1).setFill()
    NSBezierPath(roundedRect: capsule, xRadius: capsuleW / 2, yRadius: capsuleW / 2).fill()

    // Pied : part du bas de l'arceau, sans laisser d'interstice visible.
    chrome.setFill()
    let stemW = max(1, W * 0.052)
    let stemH = H * 0.105
    let stem = CGRect(x: cx - stemW / 2, y: arcBottom - stemH, width: stemW, height: stemH)
    NSBezierPath(rect: stem).fill()

    // Socle
    let baseW = W * 0.275
    let baseH = max(1, H * 0.045)
    NSBezierPath(roundedRect: CGRect(x: cx - baseW / 2, y: stem.minY - baseH * 0.5,
                                     width: baseW, height: baseH),
                 xRadius: baseH / 2, yRadius: baseH / 2).fill()

    return image
}

func writePNG(_ image: NSImage, to path: String) {
    guard let tiff = image.tiffRepresentation,
          let rep = NSBitmapImageRep(data: tiff),
          let png = rep.representation(using: .png, properties: [:]) else { return }
    try? png.write(to: URL(fileURLWithPath: path))
}

// iconutil impose ces noms exacts.
for base in [16, 32, 128, 256, 512] {
    writePNG(drawIcon(size: CGFloat(base)),
             to: "\(outDir)/icon_\(base)x\(base).png")
    writePNG(drawIcon(size: CGFloat(base * 2)),
             to: "\(outDir)/icon_\(base)x\(base)@2x.png")
}

print(outDir)
