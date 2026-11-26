# Histórico de versões

## 1.5.1

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
- **Pan não escurece mais a tela:** no Hyprland 0.57, a área de uma janela que o programa não pinta aparece preta; a moldura do zoom (e a lupa e a miniatura) passaram a limpar explicitamente o fundo para transparente.
- **Teclas animadas sem o grupo `input`:** no Hyprland, as combinações com Ctrl, Alt ou Super (até três teclas, com ou sem Shift) são avisadas pelo próprio compositor durante a gravação, sem consumir a tecla. A digitação comum, inclusive senhas, continua nunca sendo capturada.
- **A tela inicial volta a ser arrastada pela parte de cima no Hyprland** (antes só com Super + arrastar): o Hyprland anuncia, mas não atende, o arrasto feito pelo compositor; o programa passa a mover a janela por conta própria.
- **Referência do zoom acompanhando o mouse (pan) na tela:** uma moldura mostra a área que o vídeo está enquadrando, desenhada por fora do enquadramento (não aparece na gravação); com dois monitores, a miniatura ao vivo do zoom fica no monitor não gravado; a barra mostra "ZOOM 2×" enquanto o zoom está ligado.
- Diagnóstico para suporte: durante a gravação no Hyprland, a posição de cada camada (segundo o Qt e o Hyprland), os monitores e as escalas ficam em `~/.cache/gcp-capture-studio/hyprland-diagnostico.txt`.
- **Sem blocos pretos na tela:** no Hyprland, a lupa, a moldura e a miniatura do zoom não ficam mais "escondidas por máscara" (o XWayland não repassa a máscara e elas apareciam como retângulos pretos, inclusive no outro monitor); a barra recolhida e a camada de desenho também deixam de usar máscara.
- Funciona com a configuração em Lua do Hyprland (0.55 ou mais novo) e com a configuração clássica (`hyprland.conf`). Testado no Hyprland 0.57 (Lua) e 0.53 (clássica), em escala 1 e 2.

## 1.5.0

- **Nova versão para macOS** (Apple Silicon, macOS 15 ou mais novo), distribuída em `.dmg`: gravação da tela inteira e de região pelo AVFoundation, codificação por GPU (VideoToolbox), microfone e áudio em AAC nativo, atalhos globais, efeitos de clique e de teclas, barra, lupa e moldura do zoom fora do vídeo, webcam e envio ao editor de vídeo.
- No Mac, o som do sistema é gravado por um dispositivo de áudio virtual (por exemplo, o BlackHole), que aparece automaticamente como opção.
- As atualizações pelo GitHub também valem no Mac: o programa baixa o `.dmg`, confere o SHA-256 e abre a imagem para a substituição.

## 1.4.0

- **Editores instalados por Snap agora são encontrados** (por exemplo, o OpenShot no Manjaro/Arch, que fica fora do PATH). A busca passou a olhar também Flatpak, AppImage (pastas Applications/AppImages/Downloads) e os atalhos do menu de aplicativos; no macOS, a pasta Aplicativos.
- **Shotcut e OpenShot recebem a gravação já na linha do tempo**, como o Kdenlive: o programa gera o projeto do próprio editor (`.mlt` ou `.osp`) com vídeo e áudio no início da trilha.
- **Escolha do seu editor:** em Configurações › Geral › Editor de vídeo, "Escolher outro editor…" aceita o programa ou o atalho dele (`.desktop`, AppImage, `.exe`, `.lnk` ou `.app`). Se for Kdenlive, Shotcut ou OpenShot, a gravação entra na linha do tempo; outros editores recebem o arquivo de vídeo.

## 1.3.1

- **Windows: as gravações voltaram a ser salvas.** O vídeo era gravado, mas o arquivo ia parar fora da pasta escolhida e o programa avisava "Nada foi gravado". Agora ele é salvo na pasta das gravações, em MP4.
- **Windows: a gravação é enviada ao editor ao terminar.** Com o Kdenlive instalado, ele abre com o vídeo já na linha do tempo.
- **Tema escuro nas listas e menus:** em sistemas com tema claro, as listas das caixas de seleção apareciam com fundo branco e texto ilegível. O programa passa a usar as próprias cores em todas as janelas, sem depender do tema do sistema.
- **Windows testado em uso real** (Windows 11): gravação em tela inteira e por região com microfone e som do sistema, atalhos globais, zoom acompanhando o mouse com moldura e miniatura ao vivo, e envio ao Kdenlive.

## 1.3.0

- **Atualizações pelo GitHub dentro do programa:** em Configurações › Geral › Atualizações, escolha a frequência da verificação ou clique em "Verificar agora". Havendo versão nova, o programa mostra as novidades, baixa o pacote do sistema, confere o SHA-256 e instala.
- **Novos instaladores:** `.deb` (Debian/Ubuntu), `.rpm` (Fedora e compatíveis) e a primeira versão para **Windows**, além do `.pkg.tar.zst` (BigLinux/Manjaro/Arch).
- **Windows:** captura por Direct3D 11, áudio por WASAPI (microfone e som do sistema), atalhos globais, efeitos de clique e de teclas e barra fora do vídeo. Ainda não testada em máquinas reais.
- Licença GPL-3.0-or-later.

## 1.2.0

- **Zoom ao vivo visível para quem grava:** moldura sobre a tela mostrando a área enquadrada e miniatura flutuante com o vídeo já ampliado. Nenhuma das duas entra no vídeo.

## 1.1.0

- **Zoom acompanhando o mouse**, com efeito de pan suave, ligado e ajustado por atalho.
- **Lupa reescrita:** composta direto no vídeo e centrada exatamente no ponteiro; na tela, uma janela própria fora da captura mostra o conteúdo real ao vivo.
- **Áudio:** corrigidos os cortes ("som picotado") ao gravar microfone e som do sistema juntos.
- **Monitores com escala** (por exemplo, 125%) agora são gravados com as coordenadas corretas.
- **Vários monitores:** seleção de área em todos ao mesmo tempo, escolha do monitor para tela inteira e autorização de captura lembrada por monitor.
- **Barra de ferramentas:** widget recolhido com alça de arraste, nome e atalho de cada item ao passar o mouse.
- Ao enviar a gravação ao editor, o gravador se encerra para evitar gravações acidentais.

## 1.0.0

- Primeira versão: gravação de tela inteira, janela ou região, com contagem regressiva, pausa e retomada.
- Microfone e som do sistema, com medidor e teste de microfone.
- Anotações em tempo real: caneta, marca-texto, seta, linha, retângulo, elipse, texto e desfoque.
- Efeitos do mouse: clique, destaque, holofote, lupa e combinações de teclas animadas.
- Webcam flutuante em vários formatos.
- Atalhos globais personalizáveis.
- Envio automático da gravação ao Kdenlive, já na linha do tempo.
