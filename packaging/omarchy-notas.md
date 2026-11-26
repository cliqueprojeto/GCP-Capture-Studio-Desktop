Versão específica para o **Omarchy** e outras distribuições com **Hyprland**. Para BigLinux, Manjaro, Arch com KDE, Debian, Ubuntu, Fedora, Windows e macOS, continue usando a [versão 1.5.0](https://github.com/cliqueprojeto/GCP-Capture-Studio-Desktop/releases/tag/v1.5.0).

## Instalação

Baixe o arquivo `gcp-capture-studio-omarchy-1.5.1-5-any.pkg.tar.zst` abaixo e instale pelo terminal:

```bash
sudo pacman -U ~/Downloads/gcp-capture-studio-omarchy-1.5.1-5-any.pkg.tar.zst
```

Se uma versão anterior estiver instalada, o pacman faz a atualização. O SHA-256 está em `SHA256SUMS-omarchy.txt`.

## Novidades

- **Suporte ao Hyprland (Omarchy).** O programa abria cada janela como um bloco da grade do Hyprland (tela inicial, camada de anotações, barra, lupa, contagem), o que tornava a gravação inutilizável. Agora ele registra as próprias regras de janela: tudo flutua, e as camadas de gravação ficam fixas, sem borda, sombra nem animação, em todos os espaços de trabalho.
- No Hyprland, o programa sempre abre pelo XWayland (o Omarchy define `QT_QPA_PLATFORM=wayland;xcb`, e em Wayland nativo as camadas não podem ser posicionadas) e ajusta a escala em telas HiDPI quando o XWayland trabalha em pixels reais (`force_zero_scaling`, padrão do Omarchy). O editor de vídeo continua abrindo no ambiente normal da sessão.
- **Atalhos globais no Hyprland**: F9, F10, Alt+1…9 e os demais são registrados no compositor enquanto o programa está aberto e removidos ao fechar. Atalhos que você já usa na configuração do Hyprland nunca são alterados; a combinação em conflito fica de fora e é indicada em Configurações › Atalhos.
- Ponteiro, lista de janelas (gravação por janela) e escala de cada monitor vêm do próprio Hyprland, inclusive com vários monitores e escalas fracionárias. O monitor compartilhado pelo portal é reconhecido pelo nome.
- Efeito de clique no Hyprland mesmo sem acesso ao grupo `input`: o compositor avisa cada clique sem consumi-lo.
- No Hyprland, a camada de desenho, a camada de anotações, a contagem e a webcam são janelas gerenciadas (fixas, sem moldura e, as que só exibem, sem receber cliques): o Hyprland não entrega o mouse a janelas override-redirect do tipo utilitário e as posiciona errado em telas HiDPI. A barra, a webcam e a miniatura do zoom continuam clicáveis por cima da camada de desenho.
- Telas HiDPI no Hyprland (por exemplo, notebook em escala 2): as camadas cobrem exatamente o monitor e os desenhos saem sob o ponteiro (o Hyprland centraliza janelas X mapeadas em 0,0 usando o tamanho em pixels; o programa confirma a posição assim que a janela é mapeada).
- Seletor de área e de janela no Hyprland: abre como camada flutuante do tamanho do monitor (em tela cheia o Hyprland esconde as janelas de trás) e recebe o mouse mesmo com outra janela em foco.
- Zoom acompanhando o mouse (pan em tempo real) testado no Hyprland: a posição do ponteiro é lida numa thread própria, sem travar a interface nem a parada da gravação.
- Atalhos deixados por uma execução que fechou de forma inesperada são removidos na próxima abertura (ou na primeira tecla pressionada).
- **Dois ou mais monitores no Hyprland:** a barra de gravação fica no monitor que não está sendo gravado, visível, clicável e arrastável, sem entrar no vídeo. Com um monitor só, em tela cheia, ela continua oculta até Ctrl+Alt+D.
- **Desenhos visíveis com vários monitores no Hyprland:** o Hyprland abre toda janela nova no monitor em foco; se o foco estava no outro monitor ao começar a gravar, a camada de anotações nascia lá e os desenhos não apareciam no monitor gravado. Agora cada camada recebe, antes de abrir, uma regra com o monitor certo (inclusive os painéis do seletor de área, um por monitor). Funciona também com escalas diferentes entre os monitores.
- **Pan não escurece mais a tela:** no Hyprland 0.57, a moldura do zoom em janela própria aparecia como uma camada preta sobre o monitor gravado. Agora ela é desenhada na própria camada de anotações (que funciona em qualquer configuração), por fora da área enquadrada — aparece na tela e não entra no vídeo.
- **Teclas animadas sem o grupo `input`:** no Hyprland, as combinações com Ctrl, Alt ou Super (até três teclas, com ou sem Shift) são avisadas pelo próprio compositor durante a gravação, sem consumir a tecla. A digitação comum, inclusive senhas, continua nunca sendo capturada.
- **A tela inicial volta a ser arrastada pela parte de cima no Hyprland** (antes só com Super + arrastar): o Hyprland anuncia, mas não atende, o arrasto feito pelo compositor; o programa passa a mover a janela por conta própria.
- **Referência do zoom acompanhando o mouse (pan) na tela:** uma moldura mostra a área que o vídeo está enquadrando, desenhada por fora do enquadramento (não aparece na gravação); com dois monitores, a miniatura ao vivo do zoom fica no monitor não gravado; a barra mostra "ZOOM 2×" enquanto o zoom está ligado.
- Diagnóstico para suporte: durante a gravação no Hyprland, a posição de cada camada (segundo o Qt e o Hyprland), os monitores e as escalas ficam em `~/.cache/gcp-capture-studio/hyprland-diagnostico.txt`.
- **Sem blocos pretos na tela:** no Hyprland, a lupa, a moldura e a miniatura do zoom não ficam mais "escondidas por máscara" (o XWayland não repassa a máscara e elas apareciam como retângulos pretos, inclusive no outro monitor); a barra recolhida e a camada de desenho também deixam de usar máscara.
- Funciona com a configuração em Lua do Hyprland (0.55 ou mais novo) e com a configuração clássica (`hyprland.conf`). Testado no Hyprland 0.57 (Lua) e 0.53 (clássica), em escala 1 e 2.

Desenvolvido por **Bruno Albertini | [Gestão Cultural Pro](https://gestaoculturalpro.com.br/)**.
